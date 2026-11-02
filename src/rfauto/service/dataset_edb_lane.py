"""dataset_edb_lane —— 数据工厂 EDB 快车道收集器（hfss_batch 产物 → 数据集行）。

数据工厂收集链新增的 EDB 道分支（#251 谱系：①trials ②校准 samples
③surrogate_loop ④autotune ⑤api.run_once 之后的第⑥类产物通道；W3 席 6
立项）。既有收集器（dataset_service）只认 meta.json 形态 run 与工作目录
曲线形态，EDB 快车道（adapters/hfss_batch + edb_adapter）的产物目录两者
都不是——真机形态见 runs/edblane85/w1_smoke/<family>/：

- ``<stem>_spec.json``：模板发射面 spec（``template``=edb 族名、
  ``params``=设计参数 dict）——参数唯一来源（铁律 7：导入器不产生任何
  数字，只搬确定性内核/综合引擎落盘的值）；
- ``<stem>_judgment.json``：快车道判读（``readings`` 物理读数、``gates``
  判定、``touchstone`` 指针、n_ports/n_freqs/f_range_ghz 元数据）——
  目录识别主标志；
- ``state.json``：管线状态（build/solve/export/judge 分段，best-effort
  提取 design 名入 provenance）；
- ``<stem>.s<N>p``：Touchstone 产物（skrf 复读校验 + 文件自述元数据）；
- 批次根（产物目录父级）另有 ``run_summary.json`` 批次清单，本模块只读
  不依赖（批次名直接取产物目录父级目录名）。

行 schema 与物化布局**逐键对齐** dataset_service（DATASET_SCHEMA 同源
导入，points.parquet/points.h5 + dataset_manifest.yaml 同布局）——
query_dataset/list_datasets 直接可查；schema/去重/序列化/物化 helper
单源复用（禁复制，防双源漂移）。

E1 指纹（#322 对齐）：``model``=spec.template（edb 族名）／
``study_name``=批次目录**相对 runs 根的 posix 路径**（产物目录父级；一个
批次=一个战役）——用相对路径而非裸目录名，防不同战役根下的同名批次
目录（如各战役各自的 ``w1_smoke``）跨战役折叠同设计点；／
``params``=spec.params 标量规范化 JSON——去重指纹
``(model, study_name, seed, params canonical json)`` 与 materialize/
import_workdir_runs 同构：**同批次内同设计点折叠一份；跨批次（批次名
不同）不折叠**。重复收集幂等：每次调用是对在盘产物的确定性完整收集
（全量重扫重写），同指纹不重入（n_dup 计数）——数据集行数只随在盘
产物增长，不随调用次数增长。

坏目录如实处置（#122）：有 judgment 标志但缺 spec/缺 Touchstone/判读
JSON 解析失败/skrf 解析失败/params 含非有限值的候选逐个跳过并计数
（n_skipped + skip 原因逐条进 warnings），不猜不凑。cost 无统一语义置
NULL（校准样本先例）。adapter 恒 "hfss"（本道由 AEDT 批量求解产出，
构造性事实，state.build.route 存证），命中 GROUND_TRUTH_ADAPTER_TOKENS
→ 自动入 GT 标注。

数值只在确定性内核（军规 7）：本模块只做确定性收集/去重/物化，skrf
复读仅提取文件自述元数据（端口数/频点数/频率轴端点），不产生任何
物理数字。
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.dataset_service import (
    DATASET_SCHEMA,
    DEFAULT_OUT_DIR,
    GROUND_TRUTH_POLICY,
    HDF5_NAME,
    PARQUET_NAME,
    SCHEMA_VERSION,
    _aggregate_bounds,
    _canonical_json,
    _has_nonfinite,
    _import_pyarrow,
    _mtime_iso,
    _register_dataset_row,
    _resolve_registry_sync,
    _save_manifest_atomic,
    _scalar_items,
    _validate_dataset_name,
    _write_points_hdf5,
    is_ground_truth_adapter,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: 行 source/algorithm 列固定标签（查询侧按列过滤本道产物）
EDB_LANE_SOURCE = "edb_lane_import"
#: adapter 列固定标签：EDB 快车道=AEDT 批量求解（HFSS 3D Layout），
#: 构造性事实（state.build.route 存证），命中 GT 白名单词根
EDB_LANE_ADAPTER = "hfss"
#: 产物目录识别标志：``<stem>_judgment.json``（judgment 是成行主标志；
#: spec/Touchstone 缺失走候选级跳过计数，不作目录识别条件）
_JUDGMENT_SUFFIX = "_judgment.json"
#: runs 根 → 产物目录递归深度上限（edblane85/w1_smoke/branchline 实测
#: =2 层，留一层余量）
_MAX_DEPTH = 3
#: 引擎内部/缓存目录不下钻（同 workdir 导入器口径）
_SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "hfss_project"})
_SKIP_DIR_SUFFIXES = (".aedtresults", ".pyaedt", ".aedb", ".lock")
_TOUCHSTONE_RE = re.compile(r"^.+\.s(\d+)p$", re.IGNORECASE)
#: 单 JSON 读取上限（judgment/spec 是 KB 级判读/参数文件，防巨型文件）
_JSON_MAX_BYTES = 8 * 1024 * 1024
#: judgment 顶层随行的判定元数据键（在场的才收进 metrics）
_JUDGMENT_META_KEYS = ("ok", "all_pass", "n_ports", "n_freqs", "f0_on_grid",
                       "grid_step_ghz")
#: manifest ``runs_root`` 可重建说明字段（随 runs_root 同笔落盘）：相对形态
#: 解析口径 + 旧绝对路径形态的读取兼容。绝对路径/盘符永不落盘——
#: runs/datasets 是数据集条件发布面，runs_root 绝对路径是其唯一硬敏感面
#: （aurora36 W2-D 脱敏，铁律 8 同源）。
RUNS_ROOT_NOTE = (
    "runs_root 为相对本 manifest 所在数据集目录的 posix 相对路径"
    "（解析=manifest 所在目录/runs_root，resolve_dataset_runs_root 单源）；"
    "2026-10 起新生成 manifest 不落盘绝对路径与盘符（数据集条件发布脱敏），"
    "读取侧对旧绝对路径形态按存在性探测回退兼容。")


def _manifest_runs_root(root: Path, dataset_dir: Path) -> str:
    """runs 根 → manifest ``runs_root`` 落盘形态：相对数据集目录的 posix
    相对路径（缺省布局 ``runs`` vs ``runs/datasets/<name>`` → ``../../``）。

    绝对路径/盘符不落盘；跨盘等相对化不可表达场景（Windows 异盘符）落
    **空串**并靠 runs_root_note 说明重建口径——不回退写绝对路径（脱敏
    优先于便利：空串时用 collect 的 ``--runs-root`` 显式重建）。
    """
    try:
        rel = os.path.relpath(root, dataset_dir)
    except ValueError:  # 跨盘：无可表达的相对路径
        return ""
    return Path(rel).as_posix()


def resolve_dataset_runs_root(
    manifest: dict[str, Any] | None,
    manifest_path: str | Path,
    default: str | Path = "runs",
) -> Path:
    """manifest ``runs_root`` → 可用 runs 根（读取侧存在性探测回退链）。

    ①旧绝对路径形态（2026-10 前 manifest）在盘 → 原样认（机器搬移后失效
    则跳过）；②相对形态（现行写出形态）相对 **manifest 所在目录** 解析，
    在盘即认；③缺省 ``runs``（相对 cwd，collect 既有口径）在盘即认。
    全部落空 → 返回首个候选（调用方既有 ``is_dir`` 报错面接手给出准确
    消息，不在这里虚构目录）。
    """
    raw = str((manifest or {}).get("runs_root") or "").strip()
    base = Path(manifest_path).resolve().parent
    candidates: list[Path] = []
    if raw:
        p = Path(raw)
        if p.is_absolute():
            candidates.append(p)
        else:
            candidates.append(base / p)
    candidates.append(Path(default))
    for cand in candidates:
        if cand.is_dir():
            return cand.resolve()
    return candidates[0]


def _skip_dir(path: Path) -> bool:
    """引擎内部/缓存目录不下钻。"""
    if path.name in _SKIP_DIR_NAMES:
        return True
    low = path.name.lower()
    return any(low.endswith(suf) for suf in _SKIP_DIR_SUFFIXES)


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    """读 JSON 对象（超限/解析失败/非对象 → None；best-effort #105）。"""
    try:
        if path.stat().st_size > _JSON_MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _read_state_design(product_dir: Path) -> str:
    """state.json → build.design（best-effort；缺失/解析失败返回空串）。"""
    state = _load_json_dict(product_dir / "state.json")
    if state is None:
        return ""
    build = state.get("build")
    if isinstance(build, dict):
        return str(build.get("design") or "")
    return ""


def _resolve_touchstone(
    product_dir: Path, stem: str, judgment: dict[str, Any],
) -> Path | None:
    """定位候选的 Touchstone 文件（确定性次序，首个存在者胜出）：

    ① judgment ``touchstone`` 键（写侧落的指针，多为绝对路径；批次搬移后
       可能失效，存在才认）；② 产物目录内 ``<stem>.s<N>p``（大小写不敏感，
       按文件名小写排序取首，多候选消歧口径同 workdir 导入器）。
    """
    raw = judgment.get("touchstone")
    if isinstance(raw, str) and raw.strip():
        p = Path(raw)
        if p.is_file():
            return p
    try:
        candidates = sorted(
            (p for p in product_dir.iterdir()
             if p.is_file() and p.stem.lower() == stem.lower()
             and _TOUCHSTONE_RE.match(p.name)),
            key=lambda p: p.name.lower())
    except OSError:
        return None
    return candidates[0] if candidates else None


def _read_touchstone_meta(path: Path) -> dict[str, Any]:
    """skrf 复读 Touchstone → 文件自述元数据（n_ports/n_freqs/频率轴端点
    GHz）。解析失败抛异常由调用方转候选级跳过；skrf 缺失 RuntimeError
    显式报错（openems extra 惯例，不静默降级）。"""
    try:
        import skrf
    except ImportError as exc:
        raise RuntimeError(
            "EDB 道收集需要 skrf 复读 Touchstone：pip install rfauto[openems]"
            "（或 pip install scikit-rf）") from exc
    net = skrf.Network(str(path))
    n_ports = int(net.s.shape[1])
    n_freqs = int(net.s.shape[0])
    f_hz = net.frequency.f
    return {
        "n_ports": n_ports,
        "n_freqs": n_freqs,
        "f_min_ghz": float(f_hz[0]) / 1e9,
        "f_max_ghz": float(f_hz[-1]) / 1e9,
    }


def _judgment_metrics(
    judgment: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """judgment → (metrics, 非有限值键清单)。

    metrics = ``readings`` 标量（物理读数主体，确定性内核产出原样搬运）
    + 顶层判定元数据（_JUDGMENT_META_KEYS 在场的才收）+ gates 通过计数
    （n_gates_pass/n_gates_total，确定性计数非物理量）。非有限键剔除不
    吞点（workdir 导入器同口径：一个游离 NaN 不应吞掉整点）。
    """
    metrics: dict[str, Any] = {}
    dropped: list[str] = []

    def _take(key: str, v: Any) -> None:
        if isinstance(v, float) and not math.isfinite(v):
            dropped.append(key)
            return
        metrics[key] = v

    readings = judgment.get("readings")
    if isinstance(readings, dict):
        for k, v in _scalar_items(readings).items():
            _take(k, v)
    for key in _JUDGMENT_META_KEYS:
        if key in judgment:
            _take(key, judgment[key])
    gates = judgment.get("gates")
    if isinstance(gates, list) and gates:
        metrics["n_gates_total"] = len(gates)
        metrics["n_gates_pass"] = sum(
            1 for g in gates
            if isinstance(g, dict) and g.get("pass") is True)
    return metrics, dropped


def _rel_under(p: Path, root: Path) -> str:
    """路径 → 相对 root 的 posix 形态；root 外（judgment 指针可指向批次
    外部文件）与不可归一（大小写/符号链接抖动）时原样 posix 保留——指针
    仍可回溯，不因归一失败炸穿扫描（#140：PathLike 入参不假设同基）。"""
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def _scan_product_dir(
    d: Path, runs_root: Path,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """单目录 → (候选行记录, 跳过原因, 零行产物目录标签)。

    候选记录含 Path 与原始 dict（扫描态）；成行/序列化/Touchstone 复读由
    收集主函数统一处置。每个 ``<stem>_judgment.json`` 一个候选（常规=
    每目录一个）。目录含 judgment 标志但零候选成行时目录标签进第三返回
    值（坏目录如实计数，进 skipped_runs）。
    """
    rows: list[dict[str, Any]] = []
    skips: list[str] = []
    try:
        label = d.relative_to(runs_root).as_posix()
    except ValueError:  # runs_root 自身（relative 为空）按 "." 记
        label = "."
    try:
        judgment_files = sorted(
            (p for p in d.iterdir()
             if p.is_file() and p.name.lower().endswith(_JUDGMENT_SUFFIX)),
            key=lambda p: p.name.lower())
    except OSError:
        # 目录不可读：无法确认 EDB 道标志，同 workdir 静默略过
        return [], [], []
    if not judgment_files:
        return [], [], []
    # 批次目录 = 产物目录父级（产物目录在 runs 根直下、或即为 runs 根时，
    # 以产物目录自名成批次——runs 根自身不可取其父级（越出 runs 根，批次
    # 名随宿主目录漂移且跨 runs 根碰撞））；批次相对路径进 study_name
    #（E1 指纹折叠域，见模块 docstring：相对路径防同名批次跨战役折叠）
    batch_dir = d if (d == runs_root or d.parent == runs_root) else d.parent
    state_design = _read_state_design(d)
    # 候选标签 = 产物目录相对路径；同目录多 judgment（罕见）时追加 stem
    # 消歧（常规每目录一个 judgment，标签即目录路径不重复后缀）
    multi = len(judgment_files) > 1
    for jf in judgment_files:
        stem = jf.name[: -len(_JUDGMENT_SUFFIX)]
        cand_label = f"{label}/{stem}" if multi else label
        judgment = _load_json_dict(jf)
        if judgment is None:
            skips.append(f"{cand_label}/{jf.name}: 判读 JSON 解析失败，跳过")
            continue
        spec = _load_json_dict(d / f"{stem}_spec.json")
        if spec is None:
            skips.append(
                f"{cand_label}: 缺 {stem}_spec.json（无参数来源），跳过")
            continue
        params = _scalar_items(spec.get("params"))
        if not params:
            skips.append(
                f"{cand_label}: {stem}_spec.json params 段无标量参数，跳过")
            continue
        ts_path = _resolve_touchstone(d, stem, judgment)
        if ts_path is None:
            skips.append(
                f"{cand_label}: 无 Touchstone 产物"
                "（judgment.touchstone 指针失效且目录内无 <stem>.sNp），跳过")
            continue
        rows.append({
            "label": cand_label,
            "product_dir": d,
            "batch_name": batch_dir.name,
            "batch_dir": batch_dir,
            "stem": stem,
            "model": str(spec.get("template") or stem),
            "params": params,
            "judgment": judgment,
            "judgment_path": jf,
            "spec_path": d / f"{stem}_spec.json",
            "touchstone_path": ts_path,
            "state_design": state_design,
        })
    if judgment_files and not rows:
        return rows, skips, [label]
    return rows, skips, []


def _discover_products(
    runs_root: Path,
) -> tuple[list[dict[str, Any]], list[str], int, list[str]]:
    """runs 根有界递归扫 EDB 道产物目录（含 judgment 标志的目录即候选）。

    返回 (候选行记录, 跳过原因列表, 扫过的目录数, 零行产物目录标签)。
    候选按相对 posix 路径小写排序（确定性可复现）。
    """
    found: list[dict[str, Any]] = []
    skips: list[str] = []
    zero_row_dirs: list[str] = []
    n_scanned = 0

    def _visit(d: Path, depth: int) -> None:
        nonlocal n_scanned
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        subdirs = [p for p in entries if p.is_dir()]
        n_scanned += 1
        rows, dir_skips, zero_dirs = _scan_product_dir(d, runs_root)
        found.extend(rows)
        skips.extend(dir_skips)
        zero_row_dirs.extend(zero_dirs)
        if depth < _MAX_DEPTH:
            for p in subdirs:
                if not _skip_dir(p):
                    _visit(p, depth + 1)

    _visit(runs_root, 0)
    found.sort(key=lambda r: r["label"].lower())
    return found, skips, n_scanned, sorted(set(zero_row_dirs))


def discover_edb_lane_candidates(
    runs_root: str | Path = "runs",
) -> dict[str, Any]:
    """发现 runs 根下 EDB 道产物目录（只读、无副作用、不入库）。

    返回 JSON 安全 dict：ok/runs_root/n_dirs_scanned/n_candidates/
    n_skipped/skips/candidates（逐候选 label/model/batch_name/product_dir/
    spec_path/judgment_path/touchstone_path/state_design，路径均为相对
    runs_root 的 posix 形态）。收集入库走 collect_edb_lane_dataset
    （同一扫描内核）。
    """
    root = Path(runs_root).resolve()
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root}"])
    found, skips, n_scanned, _zero = _discover_products(root)
    candidates = [{
        "label": r["label"],
        "model": r["model"],
        "batch_name": r["batch_name"],
        "product_dir": _rel_under(r["product_dir"], root),
        "spec_path": _rel_under(r["spec_path"], root),
        "judgment_path": _rel_under(r["judgment_path"], root),
        "touchstone_path": _rel_under(r["touchstone_path"], root),
        "state_design": r["state_design"],
    } for r in found]
    return ok_envelope(
        runs_root=str(root),
        n_dirs_scanned=n_scanned,
        n_candidates=len(candidates),
        n_skipped=len(skips),
        skips=skips,
        candidates=candidates,
    )


def collect_edb_lane_dataset(
    run_ids: list[str] | None = None,
    *,
    name: str,
    runs_root: str | Path = "runs",
    out_dir: str | Path = DEFAULT_OUT_DIR,
    models: list[str] | None = None,
    health_gate: bool = True,
    fmt: str = "parquet",
    registry_sync: bool | None = None,
) -> dict[str, Any]:
    """把 EDB 道产物目录（hfss_batch Touchstone + judgment/spec JSON）收集
    入库为数据集（行 schema/物化布局同 materialize_dataset：``<out_dir>/
    <name>/points.parquet`` + ``dataset_manifest.yaml``，query_dataset/
    list_datasets 直接可查）。manifest 内 ``runs_root`` 为相对本 manifest
    所在目录的 posix 相对形态（绝对路径/盘符不落盘，数据集条件发布脱敏，
    RUNS_ROOT_NOTE 随行说明；信封返回值里的 runs_root 仍是运行时解析的
    本机绝对路径，只入回执不落盘）。

    run_ids：产物目录过滤（相对 runs_root 的 posix 路径或末段目录名，同
    名时按扫描序取首个；None=全部候选）。models：spec.template 族名过滤
    （None=全部；EDB 族开放增长不设封闭白名单，与 workdir 五族不同）。
    health_gate：G11 目录级健康门（默认开；单 Touchstone 目录逐目录体检，
    仅 verdict=="unhealthy" 禁入，#209 口径；体检器故障降级 unknown 不拦）。
    fmt：``parquet``|``hdf5``。registry_sync：注册表回写解析链同
    materialize_dataset（显式实参 > settings > False，best-effort）。

    幂等：每次调用是对在盘产物的确定性完整收集（全量重扫重写），去重
    指纹 (model, study_name, seed, params canonical json) 使重复收集同
    指纹不重入——数据集行数只随在盘产物增长，不随调用次数增长。

    返回 JSON 安全 dict：ok/name/dataset_dir/format/points_file/manifest/
    n_dirs_scanned/n_candidates/n_skipped/n_points/n_rows/n_dup/
    n_nonfinite_skipped/source_runs/skipped_runs/missing_runs/
    unhealthy_points/health_verdicts/per_model_rows/bounds/columns/
    ground_truth/warnings。
    """
    try:
        name = _validate_dataset_name(name)
    except ValueError as exc:
        return error_envelope([str(exc)])
    if fmt not in ("parquet", "hdf5"):
        return error_envelope([f"fmt 只允许 parquet/hdf5，收到 {fmt!r}"])
    try:
        pa, pq = _import_pyarrow()
    except RuntimeError as exc:
        return error_envelope([str(exc)])
    root = Path(runs_root).resolve()
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root}"])

    found, dir_skips, n_scanned, scan_zero_dirs = _discover_products(root)
    n_candidates_all = len(found)
    missing_runs: list[str] = []
    if run_ids is not None:
        wanted = {str(r).strip().replace("\\", "/").strip("/")
                  for r in run_ids if str(r).strip()}
        by_key: dict[str, dict[str, Any]] = {}
        for r in found:
            rel_key = _rel_under(r["product_dir"], root)
            by_key.setdefault(rel_key, r)
            by_key.setdefault(r["product_dir"].name, r)
        missing_runs = sorted(w for w in wanted if w not in by_key)
        found = [by_key[w] for w in sorted(wanted) if w in by_key]
        if not found:
            return error_envelope(
                ["指定的产物目录均不可收集（不存在/无 judgment 标志）: "
                 f"{missing_runs}"],
                missing_runs=missing_runs,
            )
    model_filter = {str(m).strip() for m in models or () if str(m).strip()}
    if model_filter:
        all_models = sorted({r["model"] for r in found})
        found = [r for r in found if r["model"] in model_filter]
        if not found:
            return error_envelope(
                [f"models 过滤后无候选（models={sorted(model_filter)}；"
                 f"在盘候选族={all_models}）"],
            )
    if not found:
        return error_envelope(
            [f"{root} 下无 EDB 道产物目录"
             "（识别标志=<stem>_judgment.json）"],
        )

    created_at = datetime.now(timezone.utc).isoformat()
    collect_errors: list[str] = list(dir_skips)
    raw_points: list[dict[str, Any]] = []
    per_dir_counts: dict[str, int] = {}
    unhealthy_points: list[str] = []
    health_verdicts: dict[str, str] = {}
    n_nonfinite_skipped = 0
    n_ct_skipped = 0  # 收集期坏候选（Touchstone 解析失败等）如实计数
    verdict_cache: dict[Path, str] = {}

    def _rel(p: Path) -> str:
        return _rel_under(p, root)

    for rec in found:
        label: str = rec["label"]
        product_dir: Path = rec["product_dir"]
        if health_gate:
            if product_dir in verdict_cache:
                verdict = verdict_cache[product_dir]
            else:
                try:
                    from rfauto.service.health_service import health_check_run

                    hc = health_check_run(
                        product_dir.name, runs_dir=product_dir.parent)
                    verdict = str(hc.get("verdict") or "unknown")
                except Exception as exc:
                    collect_errors.append(f"health_gate {label}: {exc}")
                    verdict = "unknown"
                verdict_cache[product_dir] = verdict
            health_verdicts[label] = verdict
            if verdict == "unhealthy":
                unhealthy_points.append(label)
                continue
        params: dict[str, Any] = rec["params"]
        if _has_nonfinite(params):
            n_nonfinite_skipped += 1
            collect_errors.append(
                f"{label}: params 含非有限值（NaN/±Inf），整点跳过")
            continue
        metrics, dropped = _judgment_metrics(rec["judgment"])
        if dropped:
            collect_errors.append(
                f"{label}: judgment 非有限值键 {sorted(dropped)} 已剔除"
                "（点保留）")
        try:
            params_json = _canonical_json(params)
            metrics_json = _canonical_json(metrics)
        except (ValueError, TypeError) as exc:
            collect_errors.append(
                f"{label}: params/metrics 序列化被拒（{exc}），整点跳过")
            continue
        ts_path: Path = rec["touchstone_path"]
        try:
            ts_meta = _read_touchstone_meta(ts_path)
        except RuntimeError as exc:
            return error_envelope([str(exc)])
        except Exception:
            n_ct_skipped += 1
            collect_errors.append(
                f"{label}: Touchstone 解析失败（skrf 无法读取），跳过")
            continue
        dir_key = _rel(product_dir)
        prov: dict[str, Any] = {
            "aedt_version": "",
            "ads_version": "",
            "git_sha": "",
            "run_timestamp": _mtime_iso(ts_path),
            "materialized_at": created_at,
            "run_id": product_dir.name,
            "importer": "edb_lane",
            "source_dir": _rel(product_dir),
            "batch_dir": _rel(rec["batch_dir"]),
            "spec_path": _rel(rec["spec_path"]),
            "judgment_path": _rel(rec["judgment_path"]),
            "curve_path": _rel(ts_path),
            "curve_kind": "touchstone",
            "touchstone_path": _rel(ts_path),
            "n_ports": ts_meta["n_ports"],
            "n_freqs": ts_meta["n_freqs"],
            "f_min_ghz": ts_meta["f_min_ghz"],
            "f_max_ghz": ts_meta["f_max_ghz"],
        }
        if rec["state_design"]:
            prov["state_design"] = rec["state_design"]
        raw_points.append({
            "run_id": product_dir.name,
            "model": rec["model"],
            "adapter": EDB_LANE_ADAPTER,
            "algorithm": EDB_LANE_SOURCE,
            # E1 指纹 study_name = 批次目录相对 runs 根路径（批次即战役，
            # #322）：折叠只在同一批次内发生；相对路径口径下跨战役同名
            # 批次（campaign_a/w1_smoke vs campaign_b/w1_smoke）不折叠，
            # 各留一行
            "study_name": _rel(rec["batch_dir"]),
            "seed": None,
            "params": params,
            "params_json": params_json,
            "metrics_json": metrics_json,
            "cost": None,
            "point_index": int(per_dir_counts.get(dir_key, 0)),
            "source": EDB_LANE_SOURCE,
            "provenance": prov,
        })
        per_dir_counts[dir_key] = per_dir_counts.get(dir_key, 0) + 1

    # 目录级盘点（skipped_runs=零行产物目录，同 workdir 口径）
    dir_infos: dict[str, dict[str, Any]] = {}
    seen_dirs: set[str] = set()
    for rec in found:
        key = _rel(rec["product_dir"])
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        dir_infos[key] = {
            "run_id": rec["product_dir"].name,
            "source_dir": key,
            "model": rec["model"],
            "n_points": per_dir_counts.get(key, 0),
        }
    run_infos = [dir_infos[k] for k in sorted(dir_infos)]
    skipped_runs = sorted(
        {k for k, v in dir_infos.items() if v["n_points"] == 0}
        | set(scan_zero_dirs))

    # 指纹去重（同 materialize/import_workdir_runs：
    # model/study_name/seed/params canonical json——同指纹不重入）
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
        "n_dirs_scanned": n_scanned,
        "n_candidates": n_candidates_all,
        # 坏候选如实计数：扫描期（缺 spec/缺 Touchstone/判读解析失败）+
        # 收集期（Touchstone 解析失败）；逐条原因在 warnings
        "n_skipped": len(dir_skips) + n_ct_skipped,
        "n_points": n_points,
        "n_nonfinite_skipped": n_nonfinite_skipped,
        "source_runs": run_infos,
        "skipped_runs": skipped_runs,
        "missing_runs": missing_runs,
        "unhealthy_points": unhealthy_points,
        "health_verdicts": health_verdicts,
    }
    if not rows:
        return error_envelope(
            ["没有可收集的 EDB 道产物点（候选目录均缺 spec/Touchstone/"
             "参数，或全部被健康门拦下）", *collect_errors],
            **base_counts,
        )

    bounds = _aggregate_bounds(rows)
    columns = [c for c, _t in DATASET_SCHEMA]
    n_gt_rows = 0
    gt_per_model: dict[str, int] = {}
    per_model_rows: dict[str, int] = {}
    for row in rows:
        mkey = row["model"] or "other"
        per_model_rows[mkey] = per_model_rows.get(mkey, 0) + 1
        if is_ground_truth_adapter(row["adapter"]):
            n_gt_rows += 1
            gt_per_model[row["model"]] = gt_per_model.get(row["model"], 0) + 1
    gt_block = {
        "policy": GROUND_TRUTH_POLICY,
        "n_gt_rows": n_gt_rows,
        "per_model": dict(sorted(gt_per_model.items())),
    }

    type_map = {"string": pa.string(), "int64": pa.int64(),
                "float64": pa.float64()}
    schema = pa.schema([(c, type_map[t]) for c, t in DATASET_SCHEMA])
    arrow_rows = []
    for row in rows:
        rec_row = {c: row[c] for c in columns if c != "provenance_json"}
        rec_row["provenance_json"] = json.dumps(
            row["provenance"], ensure_ascii=False, sort_keys=True)
        arrow_rows.append(rec_row)
    table = pa.Table.from_pylist(arrow_rows, schema=schema)

    dataset_dir = Path(out_dir) / name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    points_path = dataset_dir / (PARQUET_NAME if fmt == "parquet"
                                 else HDF5_NAME)
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
        "importer": "edb_lane",
        # 脱敏（aurora36 W2-D）：runs_root 落相对本 manifest 目录的 posix
        # 相对形态（RUNS_ROOT_NOTE 随行说明解析口径），绝对路径/盘符不落盘
        # ——runs/datasets 数据集条件发布面唯一硬敏感面；运行时解析走
        # resolve_dataset_runs_root（兼容旧绝对路径形态）
        "runs_root": _manifest_runs_root(root, dataset_dir),
        "runs_root_note": RUNS_ROOT_NOTE,
        "source_runs": run_infos,
        "n_dirs_scanned": n_scanned,
        "n_candidates": n_candidates_all,
        "n_skipped": len(dir_skips) + n_ct_skipped,
        "n_points": n_points,
        "n_rows": len(rows),
        "n_dup": n_dup,
        "n_nonfinite_skipped": n_nonfinite_skipped,
        "per_model_rows": dict(sorted(per_model_rows.items())),
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

    sync_enabled = _resolve_registry_sync(registry_sync)
    registry_synced = False
    if sync_enabled:
        registry_synced = _register_dataset_row(
            name, manifest_path, fmt, len(rows), visibility="private")

    result: dict[str, Any] = ok_envelope(
        name=name,
        dataset_dir=str(dataset_dir),
        format=fmt,
        points_file=str(points_path),
        manifest=str(manifest_path),
        schema_version=SCHEMA_VERSION,
        importer="edb_lane",
        runs_root=str(root),
        **base_counts,
        n_rows=len(rows),
        n_dup=n_dup,
        health_gate=bool(health_gate),
        per_model_rows=dict(sorted(per_model_rows.items())),
        bounds=bounds,
        columns=columns,
        visibility="private",
        ground_truth=gt_block,
        registry_sync=registry_synced,
    )
    if sync_enabled and not registry_synced:
        result["warnings"] = [*result.get("warnings", []),
                              "注册表回写失败（datasets 表未登记；"
                              "manifest 文件是事实源，收集不受影响）"]
    if collect_errors:
        result["warnings"] = [*result.get("warnings", []), *collect_errors]
    result["parquet" if fmt == "parquet" else "hdf5"] = str(points_path)
    return result
