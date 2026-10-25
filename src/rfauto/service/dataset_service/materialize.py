"""dataset_service.materialize —— runs/ 点级收集与物化主路径。

自 dataset_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原「收集器」「物化」两节逐字节搬迁。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.infra.par_exec import map_ordered
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
    _coerce_seed,
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
    dry_run: bool = False,
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

    runs_root = Path("runs")
    if not runs_root.is_dir():
        return error_envelope([f"runs 目录不存在: {runs_root.resolve()}"])

    missing_runs: list[str] = []
    if run_ids is not None:
        ids = sorted({str(r).strip() for r in run_ids if str(r).strip()})
        missing_runs = [rid for rid in ids if not (runs_root / rid / "meta.json").exists()]
        target_ids = [rid for rid in ids if rid not in missing_runs]
        if not target_ids:
            return error_envelope(
                [
                f"指定的 run 均无 meta.json: {missing_runs}"],
            )
    else:
        target_ids = sorted(
            d.name for d in runs_root.iterdir()
            if d.is_dir() and (d / "meta.json").exists())
        if not target_ids:
            return error_envelope([f"{runs_root.resolve()} 下无有效 run"])

    # SN-18（W6-A）：dry-run 计划面——枚举/入参校验后即回，零收集零写盘
    # （健康门逐 run 体检属收集段，计划面如实标注 not_evaluated）
    if dry_run:
        return ok_envelope(
            mode="dry-run",
            name=name,
            dataset_dir=str(Path(out_dir) / name),
            fmt=fmt,
            would_materialize=target_ids,
            n_points_planned=len(target_ids),
            missing_runs=missing_runs,
            health_gate=health_gate,
            health_gate_note="not_evaluated（计划面不跑 G11 体检）",
            adapter_note="零写入（未建数据集目录）",
        )

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
        return error_envelope([str(exc)])

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
    manifest_path = _save_manifest_atomic(dataset_dir, manifest)

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
    # XD-1（W3-B）数据集节点血缘 meta（best-effort #105，失败仅 warnings
    # 留痕不阻塞物化）：runs/datasets/<name>/meta.json 落 derived_from=
    # source_runs（边来源=调用方上下文 manifest source_runs，非目录名猜测），
    # edge_kind=dataset——数据集成为湖 lineage 图一等节点。
    try:
        from rfauto.infra.run_store import write_meta

        write_meta(
            dataset_dir,
            {"run_id": name, "model": "dataset", "status": "done",
             "adapter": "dataset_factory", "study_name": name},
            derived_from=sorted({str(ri.get("run_id")) for ri in run_infos
                                 if ri.get("run_id")}),
            edge_kind="dataset")
    except Exception as exc:
        result["warnings"] = [
            *(result.get("warnings") or []),
            f"数据集血缘 meta 写入失败（非阻断，XD-1）: {exc}"]
    return result


# ---------------------------------------------------------------------------
