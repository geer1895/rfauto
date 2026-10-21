"""dataset_service.common —— schema 常量/校验/可选依赖导入/规范化助手。

自 dataset_service.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁；io/materialize/query/workdir 各域从这里单向导入，包内零环。
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from rfauto.infra.par_exec import map_ordered as map_ordered

SCHEMA_VERSION = "2.0"
DEFAULT_OUT_DIR = Path("runs") / "datasets"
PARQUET_NAME = "points.parquet"
HDF5_NAME = "points.h5"
MANIFEST_NAME = "dataset_manifest.yaml"


def _save_manifest_atomic(dataset_dir: str | Path,
                          manifest: dict[str, Any]) -> Path:
    """manifest 原子落盘（审查 A3 P2-1，2026-10-13）：同目录 tmp +
    ``os.replace``——manifest 是数据集存在性事实源（``_load_manifest``
    返回 None → 上层报"数据集不存在"），改写既有档中途崩溃会把 points
    幸存的好档入口撕掉。campaign_manager._atomic_write_text / queue
    daemon save_queue_state 同款范式（#319 原子写家法）。返回目标路径。
    """
    import yaml

    target = Path(dataset_dir) / MANIFEST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    os.replace(tmp, target)
    return target

# 物化格式（E1 待做列①：HF（HDF5）格式与 Parquet 并列可选）。默认
# parquet——既有注册表资产（如 wp24_registry_*）manifest 无 format 键，
# 读取侧回退 parquet，资产零迁移。
DATASET_FORMATS = ("parquet", "hdf5")
DEFAULT_FORMAT = "parquet"

# 行式 schema 契约（列名, pyarrow 类型名）——manifest["columns"] 与之一致。
# params/metrics 保持 JSON 字符串（点级参数键跨器件族不同，展平会碎），
# 查询侧用 DuckDB json_extract 按需展开。
DATASET_SCHEMA: list[tuple[str, str]] = [
    ("run_id", "string"),
    ("model", "string"),
    ("adapter", "string"),
    ("algorithm", "string"),
    ("study_name", "string"),
    ("seed", "int64"),
    ("params_json", "string"),
    ("metrics_json", "string"),
    ("cost", "float64"),
    ("point_index", "int64"),
    ("source", "string"),
    ("provenance_json", "string"),
]

# ---------------------------------------------------------------------------
# ground truth 判别（WP2.4 待做列：ground truth 标注，6.3 神经算子前置）
# ---------------------------------------------------------------------------

# 真机引擎白名单词根：HFSS 为对齐基准（AGENTS 铁律），openEMS/COMSOL 为
# 真跑全波引擎，"meas" 覆盖实测导入通道（calibration:* 前缀按词根命中）。
# adapter 含 "fake" 一律不标（含 mf:fake+hfss 混合保真——行级 provenance
# 混杂廉价模型，训练数据不认）；6.3 神经算子门槛=100+ GT 点/器件族。
GROUND_TRUTH_ADAPTER_TOKENS = ("hfss", "openems", "comsol", "meas")
GROUND_TRUTH_POLICY = (
    "adapter 小写含真机引擎词根 " + "/".join(GROUND_TRUTH_ADAPTER_TOKENS)
    + " 且不含 fake（mf:fake+* 混合保真不标）"
)


def is_ground_truth_adapter(adapter: Any) -> bool:
    """按白名单策略判别单行 adapter 是否 ground truth（确定性规则）。"""
    text = str(adapter or "").lower()
    if not text or "fake" in text:
        return False
    return any(tok in text for tok in GROUND_TRUTH_ADAPTER_TOKENS)


_DATASET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_COLUMN_RE = re.compile(r"^[A-Za-z0-9_]+$")
# where 只允许单条表达式常见字符；分号/注释符等另行黑名单拦截。
# `$` 必须放行：DuckDB json_extract 的 JSON path（'$.w_mm'）在单引号
# 字面量内合法；未绑定的 $1 位置参数会被 duckdb 拒绝（查询期优雅报错）
_WHERE_ALLOWED_RE = re.compile(r"""^[A-Za-z0-9_$. ,()<>=!+*/%'"\t\r\n-]+$""")
_WHERE_FORBIDDEN = (";", "--", "/*", "*/", "`", "\\", "\x00", "||")
# SQL 关键词黑名单（大小写不敏感，审查 P1-1：字符白名单放行引号括号，
# "1=1) union all select content from read_text('x') where (1=1" 可绕过
# ——DuckDB 默认 enable_external_access，read_text/read_csv 可达任意文件；
# 复审 P1-2（FROM-first 变体）："1=1) AND EXISTS (FROM glob('../../runs**'))"
# 无任何 union/select 也完整通过旧黑名单——WHERE 片段中 FROM 无合法用途，
# 连同表函数词根 scan/glob 与谓词 exists 一并禁入（纵深防御）
_WHERE_FORBIDDEN_KEYWORDS = (
    "union", "select", "insert", "update", "delete", "read_", "write_",
    "copy", "attach", "detach", "install", "load", "call", "pragma",
    "export", "import", "create", "drop", "alter", "set ",
    "from", "scan", "glob", "exists",
)


# ---------------------------------------------------------------------------
# 可选依赖（dataset extra）——缺依赖时显式报错，不阻塞模块 import
# ---------------------------------------------------------------------------

def _import_pyarrow() -> tuple[Any, Any]:
    """返回 (pyarrow, pyarrow.parquet)；缺失时 RuntimeError 显式报错。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "数据集物化需要 pyarrow：pip install rfauto[dataset]（或 pip install pyarrow）"
        ) from exc
    return pa, pq


def _import_duckdb() -> Any:
    """返回 duckdb 模块；缺失时 RuntimeError 显式报错。"""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "数据集查询需要 duckdb：pip install rfauto[dataset]（或 pip install duckdb）"
        ) from exc
    return duckdb


def _import_h5py() -> Any:
    """返回 h5py 模块；缺失时 RuntimeError 显式报错。

    h5py 走 openems extra（WP0.1 体检实测已装）；与 dataset extra 解耦，
    不安装时只有 hdf5 格式物化/读取受限，parquet 路径零影响。
    """
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError(
            "HDF5 物化/读取需要 h5py：pip install rfauto[openems]"
            "（或 pip install h5py）") from exc
    return h5py


# ---------------------------------------------------------------------------
# 校验（service 层防注入：where 白名单字符集 + 注入子串黑名单）
# ---------------------------------------------------------------------------

def _validate_where(where: str | None) -> str:
    """校验单条 SQL WHERE 片段，返回 strip 后的安全片段；非法即 ValueError。"""
    if not isinstance(where, str) or not where.strip():
        raise ValueError("where 不能为空（仅允许单条 SQL WHERE 表达式）")
    w = where.strip()
    lowered = w.lower()
    for token in _WHERE_FORBIDDEN:
        if token in w:
            raise ValueError(
                f"where 含非法片段 {token!r}（仅允许单条 WHERE 表达式，"
                "禁止分号/注释/多语句）")
    for kw in _WHERE_FORBIDDEN_KEYWORDS:
        if kw in lowered:
            raise ValueError(
                f"where 含禁用关键词 {kw!r}（只允许对本数据集列的比较/"
                "逻辑表达式，禁止子查询/表函数/文件访问）")
    if not _WHERE_ALLOWED_RE.fullmatch(w):
        raise ValueError("where 含白名单外字符（允许：字母数字下划线空格引号"
                         "括号比较/算术运算符等）")
    return w


def _validate_dataset_name(name: str) -> str:
    """数据集名即目录名：只允许字母数字-_，防路径穿越。"""
    if not isinstance(name, str) or not _DATASET_NAME_RE.fullmatch(name.strip() or ""):
        raise ValueError(f"非法数据集名: {name!r}（只允许字母数字-_，"
                         "且以字母数字开头）")
    return name.strip()


def _validate_columns(columns: list[str] | None) -> list[str] | None:
    """列名白名单校验（标识符字符集），返回清洗后的列名列表。"""
    if columns is None:
        return None
    cleaned: list[str] = []
    for col in columns:
        c = str(col).strip()
        if not _COLUMN_RE.fullmatch(c):
            raise ValueError(f"非法列名: {col!r}（只允许字母数字下划线）")
        cleaned.append(c)
    return cleaned or None


def _canonical_json(obj: dict[str, Any]) -> str:
    """params 规范化 JSON（键排序 + 紧凑分隔符）——去重指纹的稳定基底。

    allow_nan=False（E11 未尽②根治）：非有限值（NaN/±Inf）在收集侧已被
    ``_add`` 整点拦截，此处兜底拒绝——规范外 "NaN"/"Infinity" 字面量从此
    不可能经本函数落盘（旧行为 json.dumps 默认放行，曾产出 DuckDB/skrf
    生态无法解析的伪 JSON）。
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False)


def _has_nonfinite(value: Any) -> bool:
    """递归判定容器内是否含 NaN/Inf 浮点（params 平铺但值可能嵌套）。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, dict):
        return any(_has_nonfinite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_nonfinite(v) for v in value)
    return False


# ---------------------------------------------------------------------------
# 点级数据收集（trials / calibration samples / loop best / 单次 run 产物）
# ---------------------------------------------------------------------------

def _coerce_seed(raw: Any) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
