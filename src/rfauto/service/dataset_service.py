"""dataset_service —— 数据集注册表 v2（§10.9 薄弱项 4）。

把 runs/ 下的点级数据（trials/*.json、calibration/samples.json、
surrogate_loop.json / autotune.json 的 best 点）物化为统一行式 schema
的数据集（Parquet 默认；HDF5 经 h5py 并列可选，E1 待做列①），并提供
DuckDB 直查接口（谓词下推/列裁剪；hdf5 经 Arrow 表注册走同一 SQL 管线）。

设计要点：
- 目录布局：``<out_dir>/<name>/points.parquet``（或 ``points.h5``）+
  ``dataset_manifest.yaml``（``format``/``points_file`` 记录物化格式，
  旧 manifest 无键回退 parquet）；
- 去重指纹 ``(study_name, seed, params canonical json)``：同一优化点跨
  run 复用/缓存复跑只留一份（#158 缓存语义延续），manifest 记录
  n_points/n_rows/n_dup；
- 非有限值（NaN/±Inf，params/metrics/cost 三处同口径）在收集侧整点拦截
  并计数（manifest n_nonfinite_skipped），canonical JSON 以
  allow_nan=False 兜底——规范外 "NaN"/"Infinity" 字面量与非有限 cost
  永不落盘（E11 未尽②根治；DuckDB read_parquet 统计路径下 ``cost < 阈值``
  对 NaN 行求值 TRUE，非有限 cost 落盘会挤占 warm-start collect 的
  LIMIT 窗口，故必须在写入侧拦死）；
- where 是单条 SQL WHERE 片段，service 层做白名单字符集 + 注入子串
  （分号/注释符）校验后才拼入查询；model/study_name 等值过滤走 ``?``
  参数绑定下推，值永不拼进 SQL（E11 未尽③：limit 在过滤后生效）；
- 依赖为可选 extra（dataset）：未安装时显式报错提示
  ``pip install rfauto[dataset]``（参照 smt_kriging 模式，不阻塞本模块 import）。

数值只由确定性内核产出（军规 7）：本模块只做确定性收集/去重/SQL 查询，
不引入任何估计量。
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.infra.par_exec import map_ordered

SCHEMA_VERSION = "2.0"
DEFAULT_OUT_DIR = Path("runs") / "datasets"
PARQUET_NAME = "points.parquet"
HDF5_NAME = "points.h5"
MANIFEST_NAME = "dataset_manifest.yaml"

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

# 真机引擎白名单词根：HFSS 为对齐基准（仓内铁律），openEMS/COMSOL 为
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


def _single_run_params(run_dir: Path, errors: list[str]) -> dict[str, Any]:
    """单次 run（api.run_once）的设计变量参数：recipe.snapshot.yaml 的
    ``optimization.params`` 键集（与注册表 GT 行参数列同口径）→
    ``params.<key>.value`` 取值。

    快照缺 optimization 段时退化取全部 dict 型 ``params`` 条目（标量元
    参数如 substrate 天然排除）；解析不出任何标量值返回空 dict（调用方
    跳过该 run）。解析失败只记 error 不抛（best-effort，#105）。
    """
    snap_path = run_dir / "recipe.snapshot.yaml"
    try:
        import yaml

        snap = yaml.safe_load(snap_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(
            f"{run_dir.name}/recipe.snapshot.yaml: 解析失败（{exc}）")
        return {}
    if not isinstance(snap, dict):
        errors.append(
            f"{run_dir.name}/recipe.snapshot.yaml: 不是对象，跳过")
        return {}
    params_section = snap.get("params")
    if not isinstance(params_section, dict) or not params_section:
        errors.append(
            f"{run_dir.name}/recipe.snapshot.yaml: 缺 params 段，跳过")
        return {}
    opt = snap.get("optimization")
    opt_params = opt.get("params") if isinstance(opt, dict) else None
    if isinstance(opt_params, dict) and opt_params:
        keys = [str(k) for k in opt_params]
    else:
        keys = [str(k) for k, v in params_section.items()
                if isinstance(v, dict)]
    out: dict[str, Any] = {}
    for k in keys:
        spec = params_section.get(k)
        if isinstance(spec, dict) and isinstance(
                spec.get("value"), (str, int, float, bool)):
            out[k] = spec["value"]
    if not out:
        errors.append(
            f"{run_dir.name}/recipe.snapshot.yaml: 无法从 params 段解析"
            "设计变量值，跳过")
    return out


def _coerce_cost(raw: Any) -> float | None:
    """cost 归一：非 bool 数值且有限（finite）→ float，否则 None（NULL）。

    非有限（NaN/±Inf）与"缺失"同归 None——调用方 ``_add`` 先行判定
    非有限数值并整点拦截计数，此处 None 只剩合法的"无 cost"（如校准
    样本），两者不再共享落盘通道。
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        f = float(raw)
        return f if math.isfinite(f) else None
    return None


# Touchstone 产物命名契约（api.run_once 落盘：results/params.sNp，N=端口数；
# HFSS 1 端口 patch → s1p、wilkinson 3 端口 → s3p、branchline 4 端口 → s4p）。
# 大小写不敏感（Linux 上 .S1P 也认），只认 results/ 直下的 params.* 前缀
# ——与 health_service._load_touchstone 的首选候选同口径。
_TOUCHSTONE_RE = re.compile(r"^params\.s(\d+)p$", re.IGNORECASE)


def _run_touchstone(run_dir: Path) -> tuple[str, int] | None:
    """定位单次 run 的 Touchstone 曲线产物 → (相对 run 目录的 posix 路径,
    端口数)；无产物返回 None。

    数据工厂曲线级关联（曲线级神经算子 A/B 铺路）：注册表行只存标量
    metrics，曲线本体留在 run 目录——provenance 记路径+端口数，消费侧
    ``Path(runs_root) / run_id / touchstone_path`` 直达，不再写死
    ``results/params.s1p``（wp34_neural_operator_ab 旧口径）。多份候选
    （罕见）按小写文件名排序取首个（大小写不敏感、跨平台一致，确定性
    可复现）；目录不可读一律 None（best-effort，#105）。
    """
    results_dir = run_dir / "results"
    try:
        candidates = sorted(
            (p for p in results_dir.iterdir()
             if p.is_file() and _TOUCHSTONE_RE.match(p.name)),
            key=lambda p: p.name.lower())
    except OSError:
        return None
    for path in candidates:
        m = _TOUCHSTONE_RE.match(path.name)
        if m is None:
            continue
        try:
            n_ports = int(m.group(1))
        except ValueError:
            continue
        if n_ports <= 0:
            continue
        return f"results/{path.name}", n_ports
    return None


def _collect_run_points(
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """收集单个 run 的点级数据，返回 (points, errors, n_nonfinite_skipped)。

    每个点是 {params, metrics, cost, point_index, source, algorithm} 的
    原始字典；meta 上下文由 _materialize 统一拼装。单个 run 缺产物/解析
    失败只记错误不抛（best-effort，不阻塞整库物化，#105）。

    E11 未尽②根治：params/metrics/cost 含非有限值（NaN/±Inf，含
    Infinity）的点在收集侧整点跳过并计数——写入侧拦截，规范外 JSON
    字面量与非有限 cost 不再可能进 Parquet。旧口径曾假设"cost 列是
    float64 非 JSON 面，仍由查询消费侧过滤"，实证不成立：DuckDB 1.5.5
    read_parquet 统计路径下 ``cost < 0.1`` 对 NaN 行求值 TRUE，非有限
    cost 行会挤占 warm-start collect 的 LIMIT 窗口（把合法点挤出结果）。
    """
    errors: list[str] = []
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return [], [f"{run_dir.name}: 缺 meta.json（非 rfauto run 目录，跳过）"], 0
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [f"{run_dir.name}: meta.json 解析失败（{exc}）"], 0
    if not isinstance(meta, dict):
        return [], [f"{run_dir.name}: meta.json 不是对象，跳过"], 0

    meta_algorithm = str(meta.get("algorithm") or "")
    points: list[dict[str, Any]] = []
    n_nonfinite = 0

    def _add(params: Any, metrics: Any, cost: Any, point_index: int,
             source: str, algorithm: str,
             provenance_extra: dict[str, Any] | None = None) -> None:
        nonlocal n_nonfinite
        if not isinstance(params, dict):
            errors.append(f"{run_dir.name}/{source}[{point_index}]: params 不是对象，跳过")
            return
        if _has_nonfinite(params) or _has_nonfinite(
                metrics if isinstance(metrics, dict) else {}):
            # NaN JSON 字面量根治（E11 未尽②）：整点拦截 + 计数，不落盘
            n_nonfinite += 1
            errors.append(
                f"{run_dir.name}/{source}[{point_index}]: "
                "params/metrics 含非有限值（NaN/±Inf），整点跳过")
            return
        if (isinstance(cost, (int, float)) and not isinstance(cost, bool)
                and not math.isfinite(float(cost))):
            # cost 非有限（NaN/±Inf）与 params/metrics 同口径：整点拦截 +
            # 计数（cost 列 float64 可承载 NaN，查询侧过滤对 NaN 行不可靠，
            # 见模块头/本 docstring——必须在写入侧拦死）
            n_nonfinite += 1
            errors.append(
                f"{run_dir.name}/{source}[{point_index}]: "
                "cost 非有限（NaN/±Inf），整点跳过")
            return
        points.append({
            "params": params,
            "metrics": metrics if isinstance(metrics, dict) else {},
            "cost": _coerce_cost(cost),
            "point_index": int(point_index),
            "source": source,
            "algorithm": algorithm or meta_algorithm or source,
            # provenance 附加键：字符串化落盘，唯 int（非 bool）原样保留——
            # ⑤ 的 n_ports 是计数语义，消费侧不该再 int() 反解；①—④ 不传
            # 此参数，其 provenance 逐字节不变
            "provenance_extra": (
                {str(k): (v if isinstance(v, int) and not isinstance(v, bool)
                          else str(v))
                 for k, v in provenance_extra.items()}
                if provenance_extra else None),
        })

    # ① tune 产物：trials/trial_N.json（optimizer.py 落盘契约）
    trial_files = sorted((run_dir / "trials").glob("trial_*.json")) \
        if (run_dir / "trials").is_dir() else []
    for tf in trial_files:
        try:
            data = json.loads(tf.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{run_dir.name}/{tf.name}: 解析失败（{exc}）")
            continue
        if not isinstance(data, dict):
            continue
        # trial_number 键存在但为 null 时 int(None) 会炸穿整个物化
        # （审查 P1-3：default 只救键缺失不救 None 值）——显式归一
        idx = data.get("trial_number")
        if idx is None:
            idx = len(points)
        _add(data.get("params"), data.get("metrics"), data.get("cost"),
             idx, "trials", "tune")

    # ② 校准产物：calibration/samples.json（samples 为真跑点；validation
    # 是模型预测对照，非实测样本，不收）
    calib_path = run_dir / "calibration" / "samples.json"
    if calib_path.exists():
        try:
            calib = json.loads(calib_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{run_dir.name}/calibration/samples.json: 解析失败（{exc}）")
            calib = {}
        for i, s in enumerate(calib.get("samples") or []):
            if not isinstance(s, dict):
                continue
            # 校准样本历史契约无逐点 cost（evaluate_objectives 需要 Objective
            # 对象，samples.json 存的是 dict），置 NULL 而非硬造数字（军规 7）
            _add(s.get("params"), s.get("metrics"), s.get("cost"),
                 i, "calibration_samples", "calibration")

    # ③ surrogate_loop.json 的 best 点（params/metrics/cost 齐备）
    loop_path = run_dir / "surrogate_loop.json"
    if loop_path.exists():
        try:
            loop = json.loads(loop_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{run_dir.name}/surrogate_loop.json: 解析失败（{exc}）")
            loop = {}
        best = loop.get("best")
        if isinstance(best, dict):
            _add(best.get("params"), best.get("metrics"), best.get("cost"),
                 0, "surrogate_loop_best",
                 str(loop.get("algorithm") or "surrogate_loop"))

    # ④ autotune.json 的 best 点
    at_path = run_dir / "autotune.json"
    if at_path.exists():
        try:
            at = json.loads(at_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{run_dir.name}/autotune.json: 解析失败（{exc}）")
            at = {}
        best = at.get("best")
        if isinstance(best, dict):
            _add(best.get("params"), best.get("metrics"), best.get("cost"),
                 0, "autotune_best", "autotune_loop")

    # ⑤/⑥ 单次 run / 测量 run 产物（互斥：vna_measure.json 在 → ⑥ 优先）：
    # ⑤ api.run_once 通道（WP3.4 patch HFSS GT 战役）：①—④ 均无产物且
    # meta.status=done 且 results/metrics.json 存在时，整个 run 物化为一个
    # 点——params 取 recipe.snapshot.yaml 设计变量（_single_run_params，与
    # 注册表 GT 行参数列同口径），metrics 取 results/metrics.json 的
    # metrics 段，cost 无统一语义置 NULL（可空列既有契约），provenance 带
    # run_id；results/params.sNp 在时再带 touchstone_path（相对 run 目录）
    # + n_ports（int）——数据工厂曲线级关联（曲线级神经算子 A/B 铺路），
    # 无 Touchstone 的 run 不带这两键（provenance 逐字节不变）。
    # ⑥ DP-11 测量通道：vna_measure.json 在时整个 run 物化为一个测量点
    # （adapter 列 = meta.adapter = "vna"；E1 指纹 study_name = 工作目录名
    # #322——写侧 meta 已落 study_name=run_id，物化侧另有 adapter=="vna"
    # 兜底）；params/metrics 取 vna_measure.json，cost 无语义置 NULL；
    # provenance 带 run_id/instrument/calibration 摘要 + Touchstone 指针。
    if not (trial_files or calib_path.exists() or loop_path.exists()
            or at_path.exists()):
        vna_path = run_dir / "vna_measure.json"
        status = str(meta.get("status") or "")
        if vna_path.exists() and status == "done":
            # ⑥ 测量点（DP-11）
            try:
                vm = json.loads(vna_path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(
                    f"{run_dir.name}/vna_measure.json: 解析失败（{exc}）")
                vm = None
            if isinstance(vm, dict):
                prov_extra: dict[str, Any] = {
                    "run_id": str(meta.get("run_id") or run_dir.name),
                }
                instrument = vm.get("instrument")
                calibration = vm.get("calibration")
                if isinstance(instrument, dict):
                    prov_extra["instrument_idn"] = str(instrument.get("idn") or "")
                    prov_extra["driver"] = str(instrument.get("driver") or "")
                if isinstance(calibration, dict):
                    prov_extra["calibrated"] = str(calibration.get("calibrated"))
                    prov_extra["calkit_id"] = str(calibration.get("calkit_id") or "")
                touchstone = _run_touchstone(run_dir)
                if touchstone is not None:
                    prov_extra["touchstone_path"] = touchstone[0]
                    prov_extra["n_ports"] = touchstone[1]
                _add(vm.get("params") or {}, vm.get("metrics") or {},
                     vm.get("cost"), 0, "vna_measure", "vna_measure",
                     provenance_extra=prov_extra)
        elif vna_path.exists():
            pass  # 测量 run 在跑/失败（status≠done）：静默跳过，同 ⑤ 口径
        else:
            metrics_path = run_dir / "results" / "metrics.json"
            if not metrics_path.exists():
                # done 的 run 零产物是异常信号，记 error 供上层透出（#105：
                # 只记不阻塞）；非 done（在跑/失败）静默跳过维持旧口径
                if status == "done":
                    errors.append(
                        f"{run_dir.name}: status=done 但无 trials/校准/loop/"
                        "results/metrics.json 任何产物，零点跳过")
            elif status == "done":
                try:
                    mj = json.loads(metrics_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(
                        f"{run_dir.name}/results/metrics.json: 解析失败（{exc}）")
                    mj = None
                if isinstance(mj, dict):
                    params = _single_run_params(run_dir, errors)
                    if params:
                        mj_metrics = mj.get("metrics")
                        prov_extra5: dict[str, Any] = {
                            "run_id": str(meta.get("run_id") or run_dir.name),
                        }
                        touchstone = _run_touchstone(run_dir)
                        if touchstone is not None:
                            prov_extra5["touchstone_path"] = touchstone[0]
                            prov_extra5["n_ports"] = touchstone[1]
                        _add(params, mj_metrics if isinstance(mj_metrics, dict)
                             else {}, None, 0, "run_once", "run_once",
                             provenance_extra=prov_extra5)

    return points, errors, n_nonfinite


def _run_payload(
    args: tuple[str, Path, bool, str],
) -> dict[str, Any]:
    """单 run 收集载荷（F2/df7：模块级可 pickle 纯函数，串行/并行共用）。

    输入 ``(rid, runs_root, health_gate, created_at)``；worker 内只做
    读文件+解析+纯计算（无共享可变状态，provenance 只依赖入参冻结的
    created_at）。返回聚合面 dict：

    - ``health_verdict``/``unhealthy``/``health_error``：G11 门禁结果
      （health_gate=False 时 verdict=None 不拦；体检器故障如实降级为
      不拦、错误进 health_error，#105）；
    - ``rows``：完整 raw 点行（params_json/metrics_json/provenance 已
      就绪；序列化失败点整点剔除并记 errors，与串行逐位一致）；
    - ``errors``：per-run 错误序列（收集错误 → 序列化错误，顺序即串行
      顺序）；``n_nonfinite``：非有限值整点拦截计数；
    - ``run_info``：manifest source_runs 行（空 rows 时 None）。

    空 rows 的 run 由上层记 skipped_runs（不进 run_infos/raw_points），
    unhealthy 的 run 由上层拦下（verdict 已在 payload 留档）。健康门经
    ``runs_dir=runs_root`` 显式定位（入参为父进程已 resolve 的绝对路径），
    worker 内不依赖 cwd（可复用池 worker cwd 冻结在 spawn 时刻）。
    """
    rid, runs_root, health_gate, created_at = args
    run_dir = runs_root / rid
    payload: dict[str, Any] = {
        "health_verdict": None,
        "unhealthy": False,
        "health_error": None,
        "rows": [],
        "errors": [],
        "n_nonfinite": 0,
        "run_info": None,
    }
    if health_gate:
        try:
            from rfauto.service.health_service import health_check_run

            hc = health_check_run(rid, runs_dir=runs_root)
            verdict = str(hc.get("verdict") or "unknown")
            payload["health_verdict"] = verdict
            if verdict == "unhealthy":
                payload["unhealthy"] = True
                return payload
        except Exception as exc:
            # 体检器自身故障不阻塞物化，如实降级为不拦
            payload["health_error"] = f"health_gate {rid}: {exc}"
    points, errs, n_nf = _collect_run_points(run_dir)
    payload["errors"].extend(errs)
    payload["n_nonfinite"] = n_nf
    if not points:
        return payload
    try:
        meta = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    provenance = {
        "aedt_version": str(meta.get("aedt_version") or ""),
        "ads_version": str(meta.get("ads_version") or ""),
        "git_sha": str(meta.get("git_sha") or ""),
        "run_timestamp": str(meta.get("timestamp") or ""),
        "materialized_at": created_at,
    }
    payload["run_info"] = {"run_id": rid, "n_points": len(points)}
    rows: list[dict[str, Any]] = []
    for pt in points:
        try:
            params_json = _canonical_json(pt["params"])
            metrics_json = _canonical_json(pt["metrics"])
        except (ValueError, TypeError) as exc:
            # 兜底（allow_nan=False 拒绝）：_add 拦截漏网的非有限值在此
            # 宁可缺行也不落规范外 "NaN" 字面量（#105：记警告不阻塞整库）
            payload["errors"].append(
                f"{rid}/{pt['source']}[{pt['point_index']}]: "
                f"params/metrics 序列化被拒（{exc}），整点跳过")
            continue
        prov = provenance
        prov_extra = pt.get("provenance_extra")
        if isinstance(prov_extra, dict) and prov_extra:
            # ⑤ 单次 run 点：provenance 补带 run_id（有 Touchstone 时再
            # 带 touchstone_path/n_ports）；其余类型无此键，provenance
            # 逐字节不变
            prov = {**provenance, **prov_extra}
        rows.append({
            "run_id": rid,
            "model": str(meta.get("model") or ""),
            "adapter": str(meta.get("adapter") or ""),
            "algorithm": str(pt["algorithm"]),
            # E1 指纹 study_name：DP-11 测量行（adapter="vna"）缺省取
            # 工作目录名（#322：测量战役即 study）；其余行为不变
            "study_name": str(
                meta.get("study_name")
                or (rid
                    if str(meta.get("adapter") or "") == "vna" else "")),
            "seed": _coerce_seed(meta.get("seed")),
            "params": pt["params"],
            "params_json": params_json,
            "metrics_json": metrics_json,
            "cost": pt["cost"],
            "point_index": int(pt["point_index"]),
            "source": str(pt["source"]),
            "provenance": prov,
        })
    payload["rows"] = rows
    return payload


def _aggregate_bounds(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    """跨行聚合参数空间 bounds（数值型参数的 [min, max]）。"""
    bounds: dict[str, list[float]] = {}
    for row in rows:
        for k, v in row["params"].items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            fv = float(v)
            if k not in bounds:
                bounds[k] = [fv, fv]
            else:
                if fv < bounds[k][0]:
                    bounds[k][0] = fv
                if fv > bounds[k][1]:
                    bounds[k][1] = fv
    return bounds


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


# ---------------------------------------------------------------------------
# 物化
# ---------------------------------------------------------------------------

def materialize_dataset(
    run_ids: list[str] | None = None,
    *,
    name: str,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    health_gate: bool = True,
    fmt: str = DEFAULT_FORMAT,
    registry_sync: bool | None = None,
    n_workers: int = 0,
) -> dict[str, Any]:
    """把指定 run（None=runs/ 下全部有 meta.json 的 run）的点级数据物化为
    数据集（行式 schema 见 DATASET_SCHEMA）。

    fmt 是物化格式（E1 待做列①）：``parquet``（默认，DuckDB 直查）或
    ``hdf5``（h5py 写 points.h5，与 Parquet 并列可选）；manifest 记录
    ``format``/``points_file``，查询/统计侧按 manifest 分派读取。

    n_workers（F2/df7，默认 0=串行零行为变化）：逐 run 收集（健康门+解析
    +行构建）的 run 间并行度。``<=1`` 串行；``>1`` 走 loky 可复用执行器
    （rfauto.infra.par_exec.map_ordered：进程池跨调用复用+结果按输入序
    预分配回填+worker 内 BLAS 钉 1 #258）。worker fn 是模块级纯函数
    _run_payload，串行/并行共用同一函数保证**逐 run 数值与串行逐位一致**
    （行序/错误序/计数全部按 target_ids 输入序聚合，完成序不入聚合面）；
    只做 run 间 fan-out，不在单数值内核内部并行。CLI/UI 面不动——本参数
    仅在 service API 层开放。

    health_gate（默认开，G11 门禁）：run 先过求解健康度体检
    （health_check_run），unhealthy 不入注册表（suspect-by-absence 放行
    但 verdict 留档，#209）——数据工厂的
    质量门卫（§10.17）；被拦 run 计入 unhealthy_runs 并写 manifest。

    registry_sync（R2-D-03 ⑤，默认关）：manifest 落盘后把数据集行
    upsert 进注册表 datasets 表。解析链=显式实参 > settings
    ``db.dataset_registry_sync`` > False；关闭/写库失败都不影响物化
    结果（best-effort，#105）。结果信封 ``registry_sync`` 如实透出
    是否已登记。

    返回 JSON 安全 dict：ok/name/dataset_dir/parquet（parquet 格式）或
    hdf5（hdf5 格式）/points_file/manifest/n_points/n_rows/n_dup/
    skipped_runs/missing_runs/bounds/columns。
    """
    result: dict[str, Any] = {}
    try:
        name = _validate_dataset_name(name)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)]}
    if fmt not in DATASET_FORMATS:
        return {"ok": False, "errors": [
            f"fmt 只允许 {'/'.join(DATASET_FORMATS)}，收到 {fmt!r}"]}

    try:
        pa, pq = _import_pyarrow()
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)]}

    runs_root = Path("runs")
    if not runs_root.is_dir():
        return {"ok": False, "errors": [f"runs 目录不存在: {runs_root.resolve()}"]}

    missing_runs: list[str] = []
    if run_ids is not None:
        ids = sorted({str(r).strip() for r in run_ids if str(r).strip()})
        missing_runs = [rid for rid in ids if not (runs_root / rid / "meta.json").exists()]
        target_ids = [rid for rid in ids if rid not in missing_runs]
        if not target_ids:
            return {"ok": False, "errors": [
                f"指定的 run 均无 meta.json: {missing_runs}"]}
    else:
        target_ids = sorted(
            d.name for d in runs_root.iterdir()
            if d.is_dir() and (d / "meta.json").exists())
        if not target_ids:
            return {"ok": False, "errors": [f"{runs_root.resolve()} 下无有效 run"]}

    created_at = datetime.now(timezone.utc).isoformat()
    skipped_runs: list[str] = []
    unhealthy_runs: list[str] = []
    health_verdicts: dict[str, str] = {}
    collect_errors: list[str] = []
    n_nonfinite_skipped = 0  # E11 未尽②：非有限值整点拦截计数（含 Infinity）
    raw_points: list[dict[str, Any]] = []  # 内部行：含原始 params dict
    run_infos: list[dict[str, Any]] = []

    # F2（df7）：逐 run 收集走模块级纯函数 _run_payload，串行/loky 并行
    # 共用同一函数保证逐位一致；payloads 严格按 target_ids 输入序聚合
    # （map_ordered 预分配回填，完成序永不进入聚合面）。runs_root 先收敛
    # 为绝对路径再入队——可复用池 worker 的 cwd 冻结在 spawn 时刻，父进程
    # chdir 后提交的任务会解析到旧 cwd（df7 门实测；#243 同族：路径一律
    # 绝对）；串行同参，错误消息只嵌 run_dir.name 不含 runs_root 前缀，
    # 逐位一致不受影响。
    runs_root_abs = runs_root.resolve()
    payload_args = [(rid, runs_root_abs, bool(health_gate), created_at)
                    for rid in target_ids]
    payloads = map_ordered(_run_payload, payload_args, n_workers=n_workers)
    for rid, payload in zip(target_ids, payloads, strict=True):
        if payload["health_error"]:
            collect_errors.append(payload["health_error"])
        if payload["health_verdict"] is not None:
            health_verdicts[rid] = payload["health_verdict"]
        if payload["unhealthy"]:
            # G11 门禁：真实 FAIL 证据的 run 禁入注册表（verdict 已留档；
            # "无可识别体检产物"的 run 是 suspect-by-absence 不拦——
            # 拦掉会误杀整个校准数据集，#209）
            unhealthy_runs.append(rid)
            continue
        collect_errors.extend(payload["errors"])
        n_nonfinite_skipped += payload["n_nonfinite"]
        if not payload["rows"]:
            skipped_runs.append(rid)
            continue
        run_infos.append(payload["run_info"])
        raw_points.extend(payload["rows"])

    # 指纹去重：(model, study_name, seed, params canonical json)——同点跨
    # run 复用/缓存复跑只留一份（#158 缓存语义延续）；model 进指纹防
    # 不同器件族的同泛型参数键互删（审查 P2-3）
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
    if not rows:
        result.update({
            "ok": False,
            "errors": [*["没有可物化的点级数据（指定 run 均无 "
                         "trials/校准/loop/单次 run results/metrics.json "
                         "产物）"], *collect_errors],
            "n_points": n_points,
            "n_nonfinite_skipped": n_nonfinite_skipped,
            "skipped_runs": skipped_runs,
            "missing_runs": missing_runs,
            "unhealthy_runs": unhealthy_runs,
            "health_verdicts": health_verdicts,
        })
        return result

    bounds = _aggregate_bounds(rows)
    columns = [c for c, _t in DATASET_SCHEMA]

    # ground truth 标注（WP2.4 待做列）：按白名单策略对去重后资产行逐行
    # 判别并按器件族计数——标注随物化自动落 manifest（6.3 解锁进度可见）；
    # 阈值判定（unlocked）归 dataset_insights.neural_operator_readiness。
    n_gt_rows = 0
    gt_per_model: dict[str, int] = {}
    for row in rows:
        if is_ground_truth_adapter(row["adapter"]):
            n_gt_rows += 1
            model_key = row["model"]
            gt_per_model[model_key] = gt_per_model.get(model_key, 0) + 1
    gt_block = {
        "policy": GROUND_TRUTH_POLICY,
        "n_gt_rows": n_gt_rows,
        "per_model": dict(sorted(gt_per_model.items())),
    }

    # 写 Parquet（显式 schema 保证列类型稳定，避免全空列推断成 null 类型）
    type_map = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64()}
    schema = pa.schema([(c, type_map[t]) for c, t in DATASET_SCHEMA])
    arrow_rows = []
    for row in rows:
        rec = {c: row[c] for c in columns if c != "provenance_json"}
        rec["provenance_json"] = json.dumps(
            row["provenance"], ensure_ascii=False, sort_keys=True)
        arrow_rows.append(rec)
    table = pa.Table.from_pylist(arrow_rows, schema=schema)

    out_root = Path(out_dir)
    dataset_dir = out_root / name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    points_path = dataset_dir / (
        PARQUET_NAME if fmt == "parquet" else HDF5_NAME)
    try:
        if fmt == "hdf5":
            _write_points_hdf5(points_path, table)
        else:
            pq.write_table(table, points_path)
    except RuntimeError as exc:  # 缺 h5py 等可选依赖，显式报错不半写
        return {"ok": False, "errors": [str(exc)]}

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "format": fmt,
        "points_file": points_path.name,
        "created_at": created_at,
        "source_runs": run_infos,
        "n_points": n_points,
        "n_rows": len(rows),
        "n_dup": n_dup,
        "n_nonfinite_skipped": n_nonfinite_skipped,
        "bounds": bounds,
        "columns": columns,
        "parquet": PARQUET_NAME,
        "dedup_fingerprint": "(model, study_name, seed, params canonical json)",
        "health_gate": bool(health_gate),
        "n_unhealthy_skipped": len(unhealthy_runs),
        "health_verdicts": health_verdicts,
        # 公开/私有双集（WP2.4/E1 待做列）：默认 private，公开导出前须显式
        # 置 public（dataset_insights.set_dataset_visibility）
        "visibility": "private",
        "ground_truth": gt_block,
    }
    import yaml

    manifest_path = dataset_dir / MANIFEST_NAME
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    # 注册表回写（R2-D-03 ⑤，默认关零行为变化；best-effort 不阻塞物化）
    result["registry_sync"] = False
    if _resolve_registry_sync(registry_sync):
        synced = _register_dataset_row(
            name, manifest_path, fmt, len(rows), visibility="private")
        result["registry_sync"] = synced
        if not synced:
            result["warnings"] = [*result.get("warnings", []),
                                  "注册表回写失败（datasets 表未登记；"
                                  "manifest 文件是事实源，物化不受影响）"]

    result.update({
        "ok": True,
        "name": name,
        "dataset_dir": str(dataset_dir),
        "format": fmt,
        "points_file": str(points_path),
        "manifest": str(manifest_path),
        "schema_version": SCHEMA_VERSION,
        "n_points": n_points,
        "n_rows": len(rows),
        "n_dup": n_dup,
        "n_nonfinite_skipped": n_nonfinite_skipped,
        "source_runs": run_infos,
        "skipped_runs": skipped_runs,
        "missing_runs": missing_runs,
        "unhealthy_runs": unhealthy_runs,
        "health_verdicts": health_verdicts,
        "bounds": bounds,
        "columns": columns,
        "visibility": "private",
        "ground_truth": gt_block,
    })
    if collect_errors:
        # 收集期警告随结果透出（调用方决定是否展示）
        result["warnings"] = collect_errors
    # 格式专属路径键：parquet 键向后兼容既有消费者，hdf5 键对称
    result["parquet" if fmt == "parquet" else "hdf5"] = str(points_path)
    return result


# ---------------------------------------------------------------------------
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
) -> dict[str, Any]:
    """DuckDB 直查 Parquet 数据集（谓词下推/列裁剪）。

    where 是单条 SQL WHERE 片段（如 ``cost < 0.1 and model = 'mline'``），
    经白名单校验后以 ``WHERE (片段)`` 形式拼入；columns 做标识符校验后
    实现列裁剪。model/study_name 是等值过滤便捷参：以 DuckDB 位置参数
    （``?`` 占位）安全下推——**值永不拼进 SQL 文本**（防注入面不倒退），
    且在 LIMIT 之前生效（E11 未尽③：collect 按族过滤时不再被过滤前
    截断漏样本）。返回 {ok, rows, n_rows, columns, dataset, where,
    filters, limit}。
    """
    try:
        name = _validate_dataset_name(name)
        where_sql = _validate_where(where) if where is not None else None
        cols = _validate_columns(columns)
        limit_i = int(limit)
        if limit_i < 1:
            raise ValueError(f"limit 必须 >= 1，收到 {limit!r}")
    except (ValueError, TypeError) as exc:
        return {"ok": False, "errors": [str(exc)]}

    # 等值谓词下推准备：值只进参数绑定不进 SQL；空串视为未过滤；
    # 非 str 拒绝（防静默 str() 成与列值永不相等的垃圾字面量）
    filters: dict[str, str] = {}
    for key, val in (("model", model), ("study_name", study_name)):
        if val is None:
            continue
        if not isinstance(val, str):
            return {"ok": False, "errors": [
                f"{key} 必须是 str 或 None，收到 {type(val).__name__}"]}
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
            return {"ok": False, "errors": [
                f"数据集不存在: {name}（缺 {points_path}，先 materialize）"]}

    try:
        duckdb = _import_duckdb()
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)]}

    # hdf5：经 h5py 重建 Arrow 表并注册为 DuckDB 视图，where/filters/limit
    # 与 Parquet 路径共用同一 SQL 管线（防注入面不分叉）
    arrow_table: Any = None
    if fmt == "hdf5":
        try:
            arrow_table = _read_points_hdf5(points_path, None)
        except RuntimeError as exc:
            return {"ok": False, "errors": [str(exc)]}
        except Exception:
            return {"ok": False, "errors": [
                "HDF5 点级数据读取失败（文件损坏或列缺失；原始错误不透出）"]}
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
    sql += f" LIMIT {limit_i}"

    con = duckdb.connect()
    try:
        if arrow_table is not None:
            con.register("dataset_points", arrow_table)
        cur = con.execute(sql, bind_params) if bind_params else con.execute(sql)
        col_names = [d[0] for d in cur.description]
        rows = [dict(zip(col_names, r, strict=False)) for r in cur.fetchall()]
    except Exception:  # duckdb.Error 及其子类：语法/缺列/表函数越权等查询期错误
        # 错误文案统一收敛，不透传引擎原始消息：parquet_scan 等变体会把
        # 目标路径织进 IO Error 文本，回传即存在性 oracle（任意路径探测）。
        # "sql" 是调用方自身输入（含 where 原文）的回显，非引擎内部信息，
        # 保留供归因。
        return {"ok": False, "errors": [
            "查询执行失败: where 表达式被拒绝（仅允许对本数据集列的"
            "比较/逻辑表达式；原始引擎错误不透出）"], "sql": sql}
    finally:
        con.close()

    return {
        "ok": True,
        "dataset": name,
        "format": fmt,
        "rows": rows,
        "n_rows": len(rows),
        "columns": col_names,
        "where": where_sql or "",
        "filters": filters,
        "limit": limit_i,
    }


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
_WORKDIR_PARAM_PATHS = (
    "params", "calib_params", "design_params", "design_point", "design",
    "geometry", "geom.nominal", "nominal",
)
_WORKDIR_JSON_MAX_BYTES = 4 * 1024 * 1024


def write_workdir_params_json(
    point_dir: str | Path,
    params: dict[str, Any],
    *,
    curve: str | Path | None = None,
    filename: str | None = None,
) -> Path:
    """战役脚本侧设计参数落盘——import_workdir_runs 键路径契约的**写出端**
    （与读取端 :func:`_params_from_json` 同模块单一事实源，契约不漂移）。

    在 ``point_dir``（点目录；多曲线工作目录传工作目录根）写参数 JSON，
    顶层 ``{"params": {标量 dict}}``——即 :data:`_WORKDIR_PARAM_PATHS` 最高
    优先级键路径，值全 python 标量（str/int/float/bool）。写出前经
    :func:`rfauto.infra.recipe_guard.sanitize_numpy_scalars` 收敛 np 标量
    （综合内核 np.float64 泄漏在写出端拦截）；非标量/非有限 float 显式抛
    TypeError/ValueError，不静默丢弃（#320 教训：落盘的必须是"该点实跑
    几何"，宁可在战役侧失败也不产出不可归属/不可信的参数）。

    curve：该点曲线产物路径（可选）。给定时
    ① 缺省文件名 = 曲线同名 stem.json——多曲线工作目录（hfss_marchand_anchor
    根级多 sNp 形态）靠读取端"同名 stem"归属；
    ② JSON 额外嵌 "curve" 键（相对 point_dir=JSON 所在目录的 posix 路径，
    读取端 :func:`_json_mentions_path` 显式引用双保险）。曲线在 point_dir
    内 → 相对路径不带 ``..``；在 point_dir 外 → 回退
    ``os.path.relpath`` 相对路径（R3-C-03：多子目录同名 stem 时纯文件名
    引用有歧义，如 ``../batch_a/pt1.s2p`` vs ``../batch_b/pt1.s2p``）；
    仅当相对路径不可达（Windows 跨盘符等 relpath 抛 ValueError）才退回纯
    文件名，并嵌显著字段 ``curve_ref_ambiguous: true`` 不静默。
    filename 显式给定时覆盖 ①（单曲线点目录缺省 "params.json"，传
    curve=None 即可）。

    返回写出的 JSON 路径。参数落盘是数据集入库的业务路径（非观测性），
    失败直接抛、不 best-effort。
    """
    if not isinstance(params, dict) or not params:
        raise TypeError("params 必须是非空 dict")
    from rfauto.infra.recipe_guard import sanitize_numpy_scalars

    clean = sanitize_numpy_scalars(dict(params))
    bad = {str(k): type(v).__name__ for k, v in clean.items()
           if not isinstance(v, (str, int, float, bool))}
    if bad:
        raise TypeError(f"params 含非标量值（只收 str/int/float/bool）: {bad}")
    nonfinite = sorted(k for k, v in clean.items()
                       if isinstance(v, float) and not math.isfinite(v))
    if nonfinite:
        raise ValueError(f"params 含非有限值（NaN/±Inf）: {nonfinite}")
    payload: dict[str, Any] = {"params": clean}
    if curve is not None:
        c = Path(curve)
        base = Path(point_dir).resolve()
        ambiguous = False
        try:
            ref = c.resolve().relative_to(base).as_posix()
        except ValueError:
            # 曲线在 point_dir（=JSON 所在目录）外：回退相对路径引用，
            # 多子目录同名 stem 时纯文件名有歧义（R3-C-03）。
            try:
                ref = Path(os.path.relpath(c.resolve(), base)).as_posix()
            except ValueError:
                # Windows 跨盘符等 relpath 不可达：保留纯文件名旧行为，
                # 加显著字段不静默。
                ref = c.name
                ambiguous = True
        payload["curve"] = ref
        if ambiguous:
            payload["curve_ref_ambiguous"] = True
        if filename is None:
            filename = f"{c.stem}.json"
    if filename is None:
        filename = "params.json"
    out = Path(point_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False) + "\n",
        encoding="utf-8")
    return path


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


def _scalar_items(obj: Any) -> dict[str, Any]:
    """dict 顶层标量项（str/int/float/bool，含非有限 float，交由调用方处置）。"""
    if not isinstance(obj, dict):
        return {}
    return {str(k): v for k, v in obj.items()
            if isinstance(v, (str, int, float, bool))}


def _dig_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _params_from_json(data: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """按 _WORKDIR_PARAM_PATHS 优先级取首个非空标量 dict → (params, 键路径)。"""
    for key_path in _WORKDIR_PARAM_PATHS:
        node = _dig_path(data, key_path)
        if isinstance(node, dict):
            scalars = _scalar_items(node)
            if scalars:
                return scalars, key_path
    return None


def _json_mentions_path(obj: Any, rel: str) -> bool:
    """JSON 任一字符串值是否以 rel（posix 相对路径）结尾——整段路径分量匹配，
    '/' 与 '\\' 同认（helix 仲裁 JSON 的 s1p 键是绝对 Windows 路径）。"""
    if isinstance(obj, str):
        s = obj.replace("\\", "/")
        return s == rel or s.endswith("/" + rel)
    if isinstance(obj, dict):
        return any(_json_mentions_path(v, rel) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_json_mentions_path(v, rel) for v in obj)
    return False


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    """读 JSON 对象（超 _WORKDIR_JSON_MAX_BYTES / 解析失败 / 非对象 → None）。"""
    try:
        if path.stat().st_size > _WORKDIR_JSON_MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _resolve_workdir_params(
    artifact: Path, workdir: Path, n_curves_in_dir: int,
) -> tuple[dict[str, Any], dict[str, Any], Path, str] | None:
    """曲线产物 → (params, metrics, 参数出处 JSON 路径, 键路径)；无可归属 → None。

    逐级上溯（曲线目录 → … → 工作目录根），每级两遍：① 显式引用/同名 stem
    的 JSON；② 仅单曲线目录认无引用 JSON。见模块段注释"归属规则"。
    """
    single = n_curves_in_dir == 1
    stem = artifact.stem.lower()
    level = artifact.parent
    while True:
        try:
            jsons = sorted((p for p in level.iterdir()
                            if p.is_file() and p.suffix.lower() == ".json"),
                           key=lambda p: p.name.lower())
        except OSError:
            jsons = []
        loaded: list[tuple[Path, dict[str, Any]]] = []
        for jp in jsons:
            data = _load_json_dict(jp)
            if data is not None:
                loaded.append((jp, data))
        rel_from_level = artifact.relative_to(level).as_posix()
        for jp, data in loaded:
            if jp.stem.lower() == stem or _json_mentions_path(data, rel_from_level):
                hit = _params_from_json(data)
                if hit is not None:
                    return hit[0], _scalar_items(data), jp, hit[1]
        if single:
            for jp, data in loaded:
                hit = _params_from_json(data)
                if hit is not None:
                    return hit[0], _scalar_items(data), jp, hit[1]
        if level == workdir:
            return None
        parent = level.parent
        if parent == level:
            return None
        level = parent


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
        return {"ok": False, "errors": [str(exc)]}
    if not root.is_dir():
        return {"ok": False, "errors": [f"runs 目录不存在: {root.resolve()}"]}
    scans, n_scanned, n_with_meta = _discover_workdir_scans(root, fams)
    candidates = [_serialize_scan(s) for s in scans]
    per_family: dict[str, int] = {}
    for c in candidates:
        key = c["family"] or "other"
        per_family[key] = per_family.get(key, 0) + 1
    return {
        "ok": True,
        "runs_root": str(root),
        "families": list(WORKDIR_FAMILIES),
        "n_scanned": n_scanned,
        "n_with_meta": n_with_meta,
        "n_candidates": len(candidates),
        "per_family": dict(sorted(per_family.items())),
        "candidates": candidates,
    }


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
        return {"ok": False, "errors": [str(exc)]}
    if fmt not in DATASET_FORMATS:
        return {"ok": False, "errors": [
            f"fmt 只允许 {'/'.join(DATASET_FORMATS)}，收到 {fmt!r}"]}
    try:
        pa, pq = _import_pyarrow()
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)]}
    root = Path(runs_root)
    if not root.is_dir():
        return {"ok": False, "errors": [f"runs 目录不存在: {root.resolve()}"]}

    scans, _n_scanned, _n_with_meta = _discover_workdir_scans(root, fams)
    missing_runs: list[str] = []
    if run_ids is not None:
        ids = sorted({str(r).strip() for r in run_ids if str(r).strip()})
        known = {s["run_id"] for s in scans}
        missing_runs = [rid for rid in ids if rid not in known]
        scans = [s for s in scans if s["run_id"] in ids]
        if not scans:
            return {"ok": False, "errors": [
                "指定的工作目录均不可导入（不存在/有 meta.json 走 materialize/"
                f"不属所选器件族）: {missing_runs}"],
                "missing_runs": missing_runs}
    if not scans:
        return {"ok": False, "errors": [
            f"{root.resolve()} 下无 {'/'.join(fams)} 族工作目录形态产物"]}

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
        return {
            "ok": False,
            "errors": ["没有可导入的曲线点（候选工作目录均无可归属设计参数的"
                       "曲线产物，或全部被健康门拦下）", *collect_errors],
            **base_counts,
        }

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
        return {"ok": False, "errors": [str(exc)]}

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
    import yaml

    manifest_path = dataset_dir / MANIFEST_NAME
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    # 注册表回写（R2-D-03 ⑤，默认关零行为变化；best-effort 不阻塞物化）
    sync_enabled = _resolve_registry_sync(registry_sync)
    registry_synced = False
    if sync_enabled:
        registry_synced = _register_dataset_row(
            name, manifest_path, fmt, len(rows), visibility="private")

    result: dict[str, Any] = {
        "ok": True,
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
    }
    if sync_enabled and not registry_synced:
        result["warnings"] = [*result.get("warnings", []),
                              "注册表回写失败（datasets 表未登记；"
                              "manifest 文件是事实源，导入不受影响）"]
    if collect_errors:
        result["warnings"] = [*result.get("warnings", []), *collect_errors]
    result["parquet" if fmt == "parquet" else "hdf5"] = str(points_path)
    return result
