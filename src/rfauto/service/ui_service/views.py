"""ui_service.views —— 查看数据源端点（校准工作台/跨保真/S 参数交互/报告中心/循环板）。

自 ui_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfauto.service._helpers import safe_run_id
from rfauto.service.envelope import error_envelope, ok_envelope

from .cache import (
    RUNS_DIR,
    _cached_json,
    _cached_meta,
    _cached_run_entries,
    _cached_trials_count,
    _endpoint_snapshot,
    _registry_meta_lookup,
    _run_meta_pair,
)
from .runs_recipes import tune_trials

_LOG = logging.getLogger(__name__)


# ─── 校准工作台（阶段 3.2）与跨保真对比（3.3）数据源 ────────────────────────

def calibration_runs() -> dict[str, Any]:
    """扫描 runs/ 下的校准产物清单（工作台首页列表）。

    aurora72 A2-D：目录清单/JSON 读/端点快照三层缓存（指纹+mtime 失效、
    TTL 兜底、RFAUTO_UI_CACHE=0 直通）；响应 schema 与条目顺序不变。
    R8-ENG2：条目 model/adapter 接 registry 单源（covered 态零 meta.json
    读；缺行/关闭回退文件读，字节等价），gate.json 字段仍由文件面缓存供给。
    """

    def _produce() -> list[dict[str, Any]]:
        lookup = _registry_meta_lookup()
        entries: list[dict[str, Any]] = []
        for run, is_dir in reversed(_cached_run_entries()):
            if not is_dir:
                continue
            gate = _cached_json(run / "calibration" / "gate.json")
            if not isinstance(gate, dict):
                continue
            model, adapter = _run_meta_pair(lookup, run)
            loocv = gate.get("loocv") or {}
            entries.append({
                "run_id": run.name, "model": model,
                "adapter": adapter,
                "verdict": gate.get("verdict"), "rho": loocv.get("rho"),
                "n_samples": gate.get("n_samples"),
                "n_failures": gate.get("n_failures"),
                "mesh_resolution_mm": gate.get("mesh_resolution_mm"),
                "surrogate_kind": gate.get("surrogate_kind"),
            })
        return entries

    return ok_envelope(runs=_endpoint_snapshot("calibration_runs", _produce))


def calibration_view(run_id: str) -> dict[str, Any]:
    """单次校准详情：gate + 样本点（cost 着色）+ 验证点 + 报告文本。"""
    from rfauto.core.objectives import Objective, SpecEvaluator

    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:  # P9-13 路径段守卫（单源 safe_run_id）
        return error_envelope([f"非法 run_id: {run_id!r}"])
    calib = RUNS_DIR / run_id_clean / "calibration"
    if not calib.exists():
        return error_envelope([f"该 run 无校准产物: {run_id}"])

    def _load_json(name: str) -> dict[str, Any] | None:
        p = calib / name
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    gate = _load_json("gate.json") or {}
    samples_doc = _load_json("samples.json") or {}
    report_p = calib / "report.md"
    report_md = (report_p.read_text(encoding="utf-8")
                 if report_p.exists() else None)

    objectives = [Objective(**o)
                  for o in (samples_doc.get("objectives") or [])]
    points = []
    for s in samples_doc.get("samples") or []:
        row = {k: float(v) for k, v in (s.get("params") or {}).items()}
        try:
            row["cost"] = float(SpecEvaluator.evaluate_objectives(
                s.get("metrics") or {}, objectives))
        except Exception:
            row["cost"] = None
        points.append(row)
    return ok_envelope(
        run_id=run_id, gate=gate,
        bounds=samples_doc.get("bounds") or {},
        objectives=samples_doc.get("objectives") or [],
        points=points,
        seed_sample_count=samples_doc.get("seed_sample_count"),
        augmented_from=samples_doc.get("augmented_from"),
        mesh_resolution_mm=samples_doc.get("mesh_resolution_mm"),
        validation=samples_doc.get("validation") or [],
        report_md=report_md,
    )


def cross_fidelity_view() -> dict[str, Any]:
    """跨保真对比数据（3.3）：ρ/recall 随样本量与网格档的演化曲线。

    aurora72 A2-D：原始 gate/meta/p0 文档走指纹快照缓存；行组装与 p0 阈值
    verdict 重推保持每请求现算（THRESHOLD_RHO 单源 monkeypatch 语义不变）。
    R8-ENG2：本端点需全量 meta 文档（algorithm/metrics），registry 摘要列
    不含 → meta/gate 仍走文件缓存；registry 仅经快照签名代际参与失效
    （行集/covered 态变化即重建，不残留旧来源 payload）。
    """
    import glob

    def _produce() -> dict[str, Any]:
        gate_rows: list[tuple[str, dict[str, Any]]] = []
        meta_rows: list[tuple[str, dict[str, Any]]] = []
        for run, is_dir in _cached_run_entries():
            if not is_dir:
                continue
            gate = _cached_json(run / "calibration" / "gate.json")
            if isinstance(gate, dict):
                gate_rows.append((run.name, gate))
            meta_rows.append((run.name, _cached_meta(run / "meta.json")))
        p0_rows: list[tuple[str, dict[str, Any]]] = []
        for p in sorted(glob.glob(str(Path(RUNS_DIR) / "p0_*result.json"))):
            d = _cached_json(Path(p))
            if isinstance(d, dict):
                p0_rows.append((Path(p).stem, d))
        return {"gate_rows": gate_rows, "meta_rows": meta_rows,
                "p0_rows": p0_rows}

    raw = _endpoint_snapshot("cross_fidelity_view", _produce)

    surrogate_evolution = []
    cross_evolution = []
    for run_id, gate in raw["gate_rows"]:
        loocv = gate.get("loocv") or {}
        surrogate_evolution.append({
            "run_id": run_id, "rho": loocv.get("rho"),
            "n_samples": gate.get("n_samples"),
            "mesh_resolution_mm": gate.get("mesh_resolution_mm"),
            "verdict": gate.get("verdict"),
            "surrogate_kind": gate.get("surrogate_kind"),
        })
    for run_id, m in raw["meta_rows"]:
        if m.get("algorithm") == "cross_fidelity_gate_from_asset":
            metrics = m.get("metrics") or {}
            cross_evolution.append({
                "run_id": run_id,
                "algorithm": m.get("algorithm"),
                "rho": metrics.get("rho"),
                "top5_recall": metrics.get("top5_recall"),
                "n_evaluated": metrics.get("n_evaluated"),
                "verdict": metrics.get("verdict"),
            })
    for p0_id, d in raw["p0_rows"]:
        # 阈值单源（R3-3）：verdict 重推与 p0_gate_service 门判定共用同一
        # 常量（每请求函数级 import，测试可 monkeypatch 单源验证）。
        from rfauto.service.p0_gate_service import THRESHOLD_RHO

        cross_evolution.append({
            "run_id": p0_id, "algorithm": "p0_native",
            "rho": d.get("spearman_rho"),
            "top5_recall": d.get("top5_recall"),
            "n_evaluated": d.get("n_evaluated"),
            "verdict": ("PASS" if (d.get("spearman_rho") or -1) >= THRESHOLD_RHO
                        else "FAIL"),
        })
    return ok_envelope(surrogate_evolution=surrogate_evolution,
                       cross_evolution=cross_evolution)


# ─── S 参数交互视图（3.1）/ 成本时间线（3.4）/ 报告中心（3.5）数据源 ────────

def sparams_series(
    run_id: str, mode: str = "db"
) -> dict[str, Any]:
    """单次 run 的 S 参数交互序列（3.1）。

    mode="db" 返回 |S| dB；mode="deg" 返回沿频率轴解缠绕的相位（度）。
    曲线按 S 行列全对输出，前端只渲染（图例开关/缩放/悬停读数）。
    """
    if mode not in ("db", "deg"):
        return error_envelope([f"未知 mode: {mode}（db|deg）"])
    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:  # P9-13 路径段守卫（单源 safe_run_id）
        return error_envelope([f"非法 run_id: {run_id!r}"])
    run_dir = RUNS_DIR / run_id_clean
    results = run_dir / "results"
    if not results.is_dir():
        return error_envelope([f"该 run 无 results 产物: {run_id}"])

    import numpy as np

    from rfauto.measurement.import_data import import_touchstone

    curves: list[dict[str, Any]] = []
    warning = None
    try:
        for sp in sorted(results.glob("*.s2p")) + sorted(results.glob("*.s3p")):
            data = import_touchstone(sp)
            s = data.s_params
            n = s.shape[1]
            for m in range(n):
                for k in range(n):
                    if mode == "db":
                        y = 20 * np.log10(np.abs(s[:, m, k]) + 1e-12)
                    else:
                        y = np.unwrap(np.angle(s[:, m, k])) * 180 / np.pi
                    curves.append({
                        "file": sp.name,
                        "name": f"S{m + 1}{k + 1}",
                        "freq_ghz": [round(float(x), 6)
                                     for x in data.freq_ghz],
                        "y": [round(float(v), 4) for v in y],
                    })
    except Exception as e:  # 无 Touchstone/解析失败不阻塞（返回空曲线+警告）
        warning = str(e)
    return ok_envelope(run_id=run_id, mode=mode,
                       curves=curves, warning=warning)


def external_sparams(path: str, mode: str = "db") -> dict[str, Any]:
    """外部 Touchstone 导入（WP0.3/E8）：曲线与 run 版同构，供叠加对比。

    只读操作；解析失败/非 .sNp 显式报错（errors 列表，同 sparams_series
    惯例），不阻塞页面。
    """
    if mode not in ("db", "deg"):
        return error_envelope([f"未知 mode: {mode}（db|deg）"])
    p = Path(path)  # PathLike/字符串统一收敛（#140）
    if not p.is_file():
        return error_envelope([f"文件不存在: {p}"])
    if p.suffix.lower() not in (".s1p", ".s2p", ".s3p", ".s4p"):
        return error_envelope(
            [f"非 Touchstone 文件: {p.name}（需 .s1p-.s4p）"])

    import numpy as np

    from rfauto.measurement.import_data import import_touchstone

    try:
        data = import_touchstone(p)
    except Exception as e:
        return error_envelope([f"解析失败: {p.name}: {e}"])
    s = data.s_params
    n = s.shape[1]
    curves: list[dict[str, Any]] = []
    for m in range(n):
        for k in range(n):
            if mode == "db":
                y = 20 * np.log10(np.abs(s[:, m, k]) + 1e-12)
            else:
                y = np.unwrap(np.angle(s[:, m, k])) * 180 / np.pi
            curves.append({
                "file": p.name,
                "name": f"S{m + 1}{k + 1}",
                "freq_ghz": [round(float(x), 6) for x in data.freq_ghz],
                "y": [round(float(v), 4) for v in y],
            })
    return ok_envelope(path=str(p), file=p.name, mode=mode,
                       curves=curves, n_points=int(s.shape[0]))


def sparams_compare_png(
    run_id: str, files: list[str], out_path: str | None = None,
) -> dict[str, Any]:
    """run 产物与外部 Touchstone 的 PNG 叠画对比（WP0.3/E8 验收渲染）。

    out_path 为空默认落 runs/sparams_compare/<时间戳>.png；曲线一律 dB，
    run 与外部文件以 run:/ext: 前缀区分；任一文件失败整体显式报错。
    """
    import time

    base = sparams_series(run_id, mode="db")
    if not base.get("ok"):
        return base
    run_curves = base.get("curves") or []
    if not run_curves:
        return error_envelope(
            [f"该 run 无可画的 Touchstone 曲线: {run_id}"])
    series: list[dict[str, Any]] = [
        {"label": f"run:{c['file']}·{c['name']}",
         "freq": c["freq_ghz"], "y": c["y"]}
        for c in run_curves
    ]
    for f in files:
        ext = external_sparams(f, mode="db")
        if not ext.get("ok"):
            return ext
        series += [{"label": f"ext:{c['file']}·{c['name']}",
                    "freq": c["freq_ghz"], "y": c["y"]}
                   for c in ext["curves"]]
    out = (Path(out_path) if out_path
           else Path("runs") / "sparams_compare"
           / f"{time.strftime('%Y%m%d_%H%M%S')}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")  # headless（infra/report.py 同款）
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    for s_ in series:
        ax.plot(s_["freq"], s_["y"], linewidth=1.2, label=s_["label"])
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("|S| (dB)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return ok_envelope(png=str(out), n_curves=len(series),
                       n_sources=1 + len(files))


def cost_timeline(limit: int = 300) -> dict[str, Any]:
    """run 级目标成本时间线（3.4）。

    数据源 runs_stats.query_runs（SQLite 索引）；cost 对有配方快照的
    run 用快照 objectives 确定性重算（与校准详情页同法），无快照/无
    metrics 的 run cost=null（计数返回，前端不画点）。
    """
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.service.runs_stats import query_runs

    q = query_runs(limit=limit)
    if not q.get("ok"):
        return q
    points: list[dict[str, Any]] = []
    n_without_cost = 0
    for run in reversed(q.get("runs", [])):  # 时间升序（时间线从左到右）
        cost = None
        snap_p = RUNS_DIR / run["run_id"] / "recipe.snapshot.yaml"
        metrics = run.get("metrics") or {}
        if snap_p.exists() and metrics:
            try:
                import yaml

                with open(snap_p, encoding="utf-8") as f:
                    objectives = [Objective(**o)
                                  for o in (yaml.safe_load(f)
                                            or {}).get("objectives") or []]
                if objectives:
                    cost = float(SpecEvaluator.evaluate_objectives(
                        metrics, objectives))
            except Exception:
                cost = None
        if cost is None:
            n_without_cost += 1
            continue
        points.append({
            "run_id": run["run_id"], "timestamp": run["timestamp"],
            "adapter": run["adapter"], "model": run["model"],
            "cost": cost,
        })
    tr = tune_trials()
    return ok_envelope(points=points,
                       n_without_cost=n_without_cost,
                       latest_tune_run_id=tr.get("run_id"),
                       latest_tune_trials=tr.get("trials", [])[-200:])


_REPORT_FILES = (
    ("run", "report.md"),
    ("sim_ci", "sim_ci_report.md"),
    ("calibration", "calibration/report.md"),
)


def list_reports() -> dict[str, Any]:
    """报告中心清单（3.5）：扫描 runs/ 下人读报告（kind+路径+元信息）。

    aurora72 A2-D：端点快照缓存（指纹+mtime 失效；报告文件同名就地改写的
    size/mtime 最迟 TTL 秒后可见；RFAUTO_UI_CACHE=0 直通）；schema 不变。
    R8-ENG2：条目 model 接 registry 单源（covered 态零 meta.json 读；
    缺行/关闭回退文件读，字节等价）；报告文件存在性/size/mtime 仍走文件面。
    """

    def _produce() -> list[dict[str, Any]]:
        lookup = _registry_meta_lookup()
        entries: list[dict[str, Any]] = []
        for run, is_dir in reversed(_cached_run_entries()):
            if not is_dir:
                continue
            model = _run_meta_pair(lookup, run)[0]
            for kind, rel in _REPORT_FILES:
                p = run / rel
                if not p.is_file():
                    continue
                try:
                    size = p.stat().st_size
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                entries.append({
                    "run_id": run.name, "kind": kind, "model": model,
                    "path": str(p).replace("\\", "/"),
                    "size_bytes": size, "mtime": mtime,
                })
        return entries

    return ok_envelope(reports=_endpoint_snapshot("list_reports", _produce))


def report_content(path: str) -> dict[str, Any]:
    """读取单份报告文本（路径白名单：只允许 runs/ 下的 .md）。

    附带 run_id（路径首段），报告中心前端据此把相对图片引用重写到
    /api/runs/<run_id>/figs/ 白名单路由（修复裂图，2026-09-15 UI 批）。
    """
    p = Path(path)
    try:
        resolved = p.resolve()
        rel = resolved.relative_to(RUNS_DIR.resolve())
    except (ValueError, OSError):
        return error_envelope([f"路径越界（只允许 runs/）: {path}"])
    if resolved.suffix != ".md" or not resolved.is_file():
        return error_envelope([f"不是 runs/ 下的 .md 报告: {path}"])
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as e:
        return error_envelope([f"报告读取失败: {e}"])
    run_id = rel.parts[0] if len(rel.parts) > 1 else None
    return ok_envelope(path=str(resolved).replace("\\", "/"),
                       run_id=run_id, content=text)


#: 报告图片白名单：只服务 runs/<run_id>/results/figs/ 下的位图/矢量图
_FIG_SUFFIXES = (".png", ".svg")
#: report.md 里图片引用的固定子目录（裂图修复：相对引用重写到白名单路由）
REPORT_FIG_SUBDIR = "results/figs"
#: pareto_runs 目录扫描硬上限（防 runs/ 失控增长拖垮下拉；正常远小于此）
_PARETO_RUNS_SCAN_CAP = 4000


def run_fig_file(run_id: str, name: str) -> Path | None:
    """报告图片白名单解析（项 2 裂图修复，路径穿越防护）。

    只允许 runs/<run_id>/results/figs/ 下的 .png/.svg：
    - run_id 必须是单段目录名（守卫单源 safe_run_id，P9-13）；
    - name 是 report.md 里的相对引用（如 results/figs/s11_curve.png，
      也接受裸文件名），resolve 后必须仍落在该 run 的 figs 目录内；
    - 文件不存在/后缀不符 → None（路由层转 404，前端显示占位）。
    """
    run_id = safe_run_id(run_id)
    name = str(name).replace("\\", "/").strip().lstrip("/")
    if not run_id or not name:
        return None
    if "/" not in name:
        name = f"{REPORT_FIG_SUBDIR}/{name}"
    figs_root = (RUNS_DIR / run_id / REPORT_FIG_SUBDIR).resolve()
    try:
        candidate = (RUNS_DIR / run_id / name).resolve()
        candidate.relative_to(figs_root)
    except (ValueError, OSError):
        return None
    if candidate.suffix.lower() not in _FIG_SUFFIXES or not candidate.is_file():
        return None
    return candidate


def pareto_runs(limit: int = 200) -> dict[str, Any]:
    """优化洞察页 run 清单（项 3：下拉过滤与分组）。

    三档 tier：front（有 results/pareto_front.json，直读前沿）>
    trials（有 trials/*.json，可现算约束 Pareto）> single（单点仿真，
    无优化轨迹）。优化 run 排前、单点 run 排后——前端据此分组下拉、
    无数据 run 标注并给人话空态。

    aurora72 A2-D：快照缓存存 limit 切片前的全量 entries（不同 limit
    共享一次扫描）；指纹+mtime 失效；trials 计数 per-run 目录 mtime
    键控缓存；schema 与排序不变。R8-ENG2：条目 model/adapter 接 registry
    单源（covered 态零 meta.json 读；缺行/关闭回退文件读，字节等价）；
    tier 判定（pareto_front.json/trials 计数）仍走文件面（库内无此信息）。
    """

    def _produce() -> list[dict[str, Any]]:
        lookup = _registry_meta_lookup()
        entries: list[dict[str, Any]] = []
        # 全量扫目录再排序后切 limit：字典序里 w* 等字母目录排在日期目录前，
        # 若先切片会被字母目录占满名额把日期 run 截掉（tier 语义优先于字典序）
        run_dirs = [p for p, is_dir in reversed(_cached_run_entries())
                    if is_dir]
        if len(run_dirs) > _PARETO_RUNS_SCAN_CAP:  # 内部扫描硬上限（防失控）
            run_dirs = run_dirs[:_PARETO_RUNS_SCAN_CAP]
        for run in run_dirs:
            has_front = (run / "results" / "pareto_front.json").is_file()
            trials_dir = run / "trials"
            n_trials = (_cached_trials_count(trials_dir)
                        if trials_dir.is_dir() else 0)
            tier = "front" if has_front else ("trials" if n_trials else "single")
            model, adapter = _run_meta_pair(lookup, run)
            entries.append({
                "run_id": run.name, "model": model,
                "adapter": adapter,
                "tier": tier, "has_pareto": has_front, "n_trials": n_trials,
            })
        return entries

    entries = _endpoint_snapshot("pareto_runs", _produce)
    tier_rank = {"front": 0, "trials": 1, "single": 2}
    # 两次稳定排序：tier 内 run_id 倒序（新 run 在前），tier 升序（优化 run 排前）
    entries.sort(key=lambda e: e["run_id"], reverse=True)
    entries.sort(key=lambda e: tier_rank.get(e["tier"], 3))
    return ok_envelope(runs=entries[:max(0, int(limit))])


def loop_boards(limit: int = 20) -> dict[str, Any]:
    """执行看板清单（WP3.5 v1.2 增强②；自治环步骤可视的列表侧）。"""
    from rfauto.service.loop_board import list_boards

    return list_boards(limit=limit)


def loop_board_view(board_id: str) -> dict[str, Any]:
    """单个执行看板：当前步骤 + 里程碑验收表 + 步骤历史。"""
    from rfauto.service.loop_board import read_board

    return read_board(board_id)


def loop_board_control(board_id: str, action: str) -> dict[str, Any]:
    """向执行看板发控制命令（pause/resume/takeover），环在步骤边界响应。"""
    from rfauto.service.loop_board import board_control

    return board_control(board_id, action)
