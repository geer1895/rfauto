"""ui_service.insights —— 场可视化/Smith 圆图/patch η 门/优化洞察（Pareto/热图）/数据集·标定锚·UQ 三页端点。

自 ui_service.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rfauto.service._helpers import load_run_trials, safe_run_id
from rfauto.service.envelope import error_envelope, ok_envelope

from .cache import (
    _H5_PROBE_CACHE,
    _RUN_SCAN_CACHE,
    RUNS_DIR,
    _cached_run_entries,
    _endpoint_snapshot,
    _file_signature,
)

_LOG = logging.getLogger(__name__)


# ═══ G9 场可视化 3D + Smith 圆图（§10.7 G9 余量；服务层 JSON 进出）═══════
#
# 数据源：openEMS 真跑 run 的 DumpHDF5 产物（nf2ff 盒六面 nf2ff_E_*.h5、
# SAR_raw.h5/SAR_1g.h5 体 dump）+ CalcNF2FF 原生 farfield_3d.h5/nf2ff.h5；
# 数值全部由 infra.visualization 确定性内核变换（|E| 包络/切片/等值面/dB
# 归一/Γ→Z），本层只做产物定位与 JSON 组装。任一子产物失败只记 warning
# （#105 best-effort），不阻塞页面。

#: DumpHDF5 浅层落盘位置（run 根=模板脚本目录，fdtd/=SIM_PATH），免全树 rglob
FIELD_DUMP_SUBDIRS: tuple[str, ...] = ("", "fdtd")
#: CalcNF2FF 原生 HDF5 名（优先 3D 全球面，其次 φ 切面）
FARFIELD_H5_NAMES: tuple[str, ...] = ("farfield_3d.h5", "nf2ff.h5")


def _is_field_dump(path: Path) -> bool:
    """DumpHDF5 契约辨识：Mesh + FieldData 组（nf2ff.h5 是 nf2ff 组，排除）。

    架构批 A2-D：h5py 开文件探测按 (mtime_ns, size) 键控缓存——250GB
    面上百 MB 级 dump 的头部读取命中后零开销；文件变化即刻失效。
    """

    def _produce() -> bool:
        try:
            import h5py

            with h5py.File(path, "r") as h:
                return "Mesh" in h and "FieldData" in h
        except Exception:
            return False

    return bool(_H5_PROBE_CACHE.get(
        (os.path.normcase(str(path)),), _file_signature(path), _produce))


def _field_dump_candidates(run_dir: Path) -> list[Path]:
    """run 根与 fdtd/ 下的场 dump（体 dump 优先于 nf2ff 盒面 dump，再按名排序）。

    架构批 A2-D：per-run 目录 mtime 键控缓存——命中免 *.h5 枚举与探测；
    目录内 h5 新增/删除改目录 mtime 即刻失效；返回副本防调用方 mutate。
    """
    try:
        run_sig: int | None = run_dir.stat().st_mtime_ns
    except OSError:
        run_sig = None
    try:
        fdtd_sig: int | None = (run_dir / "fdtd").stat().st_mtime_ns
    except OSError:
        fdtd_sig = None

    def _produce() -> list[Path]:
        found: list[Path] = []
        for sub in FIELD_DUMP_SUBDIRS:
            base = run_dir / sub if sub else run_dir
            if not base.is_dir():
                continue
            found.extend(p for p in sorted(base.glob("*.h5"))
                         if _is_field_dump(p))
        return sorted(found, key=lambda p: (p.name.startswith("nf2ff_"), p.name))

    cached = _RUN_SCAN_CACHE.get(
        (os.path.normcase(str(run_dir)), "field_dumps"),
        None if run_sig is None else (run_sig, fdtd_sig), _produce)
    return list(cached)


def _farfield_h5(run_dir: Path) -> Path | None:
    for name in FARFIELD_H5_NAMES:
        for sub in FIELD_DUMP_SUBDIRS:
            cand = (run_dir / sub if sub else run_dir) / name
            if cand.is_file():
                return cand
    return None


def _viz3d_available() -> bool:
    from rfauto.infra.visualization import viz3d_available

    return viz3d_available()


# ─── patch 族修正后 η 物理合理门（2026-09-17 门复议，followUp ⑤）──
#
# 数字依据链（坑 #118：裁判 = 收敛真跑实测 + 独立来源解析式，不是自己的推导）：
# * 解析式（Balanis 单腔损耗分解，PEC 导体 Q_c→∞）：η = Q_d/(Q_d+Q_rad)，
#   Q_d = 1/tanδ；RO4350B tanδ=0.0037 → Q_d = 270.27。
# * 实测锚 runs/patch_field_smoke_recheck/_smoke_result.json（真收敛：能量
#   −60.3dB、nf2ff 盒顶余量 40.5mm ≥ λ/4 33.9mm、两口径 Dmax 差 0.015dB）：
#   η_corr = 0.5711 → Q_rad = Q_d·(1−η)/η = 203（≈200）。
# * 伪象幅度 runs/patch_field_smoke（同几何、仅 AIR_TOP 26.79→45mm 差异的
#   紧贴盒轮）：η_corr 0.6215 = 较锚值 Prad 虚高 +8.82% → 守卫带取该观测值。
# * 下沿 = Q_d/(Q_d + 203×1.0882) = 270.27/491.13 = 0.5503 ≈ 0.55（旧门 0.62
#   出自 W2⑥a "Q_rad~60–80" 估计，被实测 2.5× 否定）；上沿保留 0.79（对应
#   Q_rad≈72，即 Prad 较锚值虚高 ~2.8× 才触线，作镜像修正失效/盒伪象检测线）。
# 作用域：仅 template=="patch"（dipole 全包盒 η=0.99 属另一族，不套此窗）。
PATCH_ETA_GATE: tuple[float, float] = (0.55, 0.79)
#: 门的实测锚（回归钉用；两轮真跑数字均出自 runs/ 判读 json，非推导）
PATCH_ETA_GATE_BASIS: dict[str, float] = {
    "tan_delta": 0.0037,
    "eta_anchor_converged": 0.5711170472292979,   # patch_field_smoke_recheck
    "eta_tight_box_run": 0.621490823071419,       # patch_field_smoke（紧贴盒）
}


def patch_eta_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    """修正后 η 的 patch 族物理合理性判读（确定性比较；η 缺失如实 unknown）。

    返回 {gate:[lo,hi], value, ok(True/False/None), reason}；ok=None 表示不可
    判读（P_acc 缺失/非正 → η None），不虚构（#105）。
    """
    lo, hi = PATCH_ETA_GATE
    eta = metrics.get("efficiency")
    out: dict[str, Any] = {"gate": [lo, hi], "value": eta, "ok": None, "reason": ""}
    if eta is None:
        out["reason"] = "η 不可得（P_acc 缺失或非正）"
        return out
    eta = float(eta)
    out["value"] = eta
    if not (0.0 < eta < 1.0):
        out["ok"] = False
        out["reason"] = f"η={eta:.4f} 非物理（须 0<η<1；≥1 常为 PEC 镜像双计未修正）"
    elif eta < lo:
        out["ok"] = False
        out["reason"] = f"η={eta:.4f} 低于下沿 {lo}（欠辐射/收敛或盒余量存疑）"
    elif eta > hi:
        out["ok"] = False
        out["reason"] = f"η={eta:.4f} 超上沿 {hi}（Prad 虚高伪象嫌疑）"
    else:
        out["ok"] = True
        out["reason"] = f"η={eta:.4f} 落 [{lo}, {hi}]"
    return out


def field_runs(limit: int = 50) -> dict[str, Any]:
    """含场 dump 产物的 run 清单（场可视化页下拉；战役多 run 逐个可选）。

    架构批 A2-D：h5 探测（_is_field_dump）与 per-run 候选清单走
    (mtime_ns, size)/目录 mtime 键控缓存，端点快照指纹失效（真树冷跑
    9.3s → 命中毫秒级）；RFAUTO_UI_CACHE=0 直通；schema 不变。
    R8-ENG2：本端点条目不含 meta 字段、registry 库内亦无场 dump 信息，
    payload 组装不接线；registry 仅经快照签名代际参与失效。
    """

    def _produce() -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for run_dir, is_dir in _cached_run_entries():
            if not is_dir:
                continue
            dumps = _field_dump_candidates(run_dir)
            if not dumps:
                continue
            hits.append({
                "run_id": run_dir.name,
                "dumps": [d.name for d in dumps],
                "n_dumps": len(dumps),
                "has_farfield_h5": _farfield_h5(run_dir) is not None,
                "mtime": max(d.stat().st_mtime for d in dumps),
            })
        return hits

    hits = _endpoint_snapshot("field_runs", _produce)
    hits.sort(key=lambda h: -h["mtime"])
    return ok_envelope(runs=hits[: max(1, int(limit))],
                       viz3d_available=_viz3d_available())


def field_view(
    run_id: str,
    dump: str | None = None,
    engine: str = "auto",
    levels_db: tuple[float, ...] | None = None,
    slice_index: dict[str, int] | None = None,
) -> dict[str, Any]:
    """单 run 场可视化视图：切片热图 + 等值面/等值线 + 远场 3D 图 + D4 指标。

    dump 缺省取候选首个（体 dump 优先）；engine=auto|pyvista|numpy 透传内核；
    levels_db 等值电平（相对峰值 dB）；slice_index 各轴切片索引（缺省中面）。
    远场 3D 图（farfield_3d.h5）与 farfield_meta.json 指标为 D4 联动，缺失
    置 None 并记 warning。指标经 PEC 地镜像修正（core.farfield.correct_pec_mirror，
    与 nf2ff_service 同一函数；修正前原值留 raw）并附 patch 族 η 门判读 eta_gate
    （非 patch 模板为 None）。
    """
    from rfauto.infra.visualization import (
        DEFAULT_ISO_LEVELS_DB,
        farfield_pattern_from_h5,
        field_isosurface,
        field_slices,
        read_field_dump,
    )

    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:  # P9-13 路径段守卫（单源 safe_run_id）
        return error_envelope([f"非法 run_id: {run_id!r}"])
    run_dir = RUNS_DIR / run_id_clean
    if not run_dir.is_dir():
        return error_envelope([f"run 不存在: {run_id}"])
    dumps = _field_dump_candidates(run_dir)
    if not dumps:
        return error_envelope(
            [f"该 run 无 openEMS 场 dump（需 far_field/sar=True 或 DumpHDF5 真跑）: {run_id}"])
    if dump:
        picked = next((d for d in dumps if d.name == dump), None)
        if picked is None:
            return error_envelope([f"dump 不存在: {dump}（可选 {[d.name for d in dumps]}）"])
    else:
        picked = dumps[0]

    warnings: list[str] = []
    try:
        vol = read_field_dump(picked)
    except Exception as e:
        return error_envelope([f"dump 读取失败 {picked.name}: {e}"])

    levels = tuple(float(v) for v in levels_db) if levels_db else DEFAULT_ISO_LEVELS_DB
    try:
        slices = field_slices(vol, indices=slice_index)
    except Exception as e:  # 切片是主视图；失败如实报错
        return error_envelope([f"切片失败: {e}"])
    try:
        iso = field_isosurface(vol, levels_db=levels, engine=engine)
        warnings.extend(iso.get("warnings") or [])
    except Exception as e:  # 等值面 best-effort（#105）
        iso = error_envelope([str(e)], engine=engine)
        warnings.append(f"等值面失败: {e}")

    pattern3d: dict[str, Any] | None = None
    ff_h5 = _farfield_h5(run_dir)
    if ff_h5 is not None:
        try:
            pattern3d = farfield_pattern_from_h5(ff_h5)
        except Exception as e:
            warnings.append(f"远场 HDF5 解析失败 {ff_h5.name}: {e}")

    farfield_metrics: dict[str, Any] | None = None
    try:
        from rfauto.core.farfield import (
            FARFIELD_META_NAME,
            correct_pec_mirror,
            find_artifacts,
        )

        found = find_artifacts(run_dir)
        if FARFIELD_META_NAME in found:
            meta = json.loads(found[FARFIELD_META_NAME].read_text(encoding="utf-8"))
            if meta.get("ok"):
                # PEC 地镜像修正：与 nf2ff_service._read_metrics 同一内核函数
                # （core.farfield.correct_pec_mirror，#249），修正前原值留 raw。
                fixed = correct_pec_mirror(meta)
                farfield_metrics = {k: fixed.get(k) for k in
                                    ("f_res_ghz", "dmax_dbi", "gain_max_dbi",
                                     "efficiency", "power_budget_closure", "template")}
                farfield_metrics["pec_mirror_factor"] = fixed.get("pec_mirror_factor", 1.0)
                if "raw" in fixed:
                    farfield_metrics["raw"] = fixed["raw"]
                farfield_metrics["eta_gate"] = (
                    patch_eta_gate(farfield_metrics)
                    if farfield_metrics.get("template") == "patch" else None)
    except Exception as e:
        warnings.append(f"farfield_meta.json 解析失败: {e}")

    return ok_envelope(
        run_id=run_id,
        dumps=[d.name for d in dumps],
        selected=picked.name,
        volume={
            "shape": list(vol.shape),
            "domain": vol.domain,
            "dump_type": vol.dump_type,
            "frequency_ghz": (vol.frequency_hz / 1e9 if vol.frequency_hz else None),
            "n_timesteps": vol.n_timesteps,
            "peak": iso.get("peak", vol.peak),
            "x_mm": [round(float(v) * 1e3, 4) for v in (vol.x_m[0], vol.x_m[-1])],
            "y_mm": [round(float(v) * 1e3, 4) for v in (vol.y_m[0], vol.y_m[-1])],
            "z_mm": [round(float(v) * 1e3, 4) for v in (vol.z_m[0], vol.z_m[-1])],
        },
        slices=slices,
        isosurface=iso,
        engine=iso.get("engine", engine),
        pattern3d=pattern3d,
        farfield_metrics=farfield_metrics,
        polar_link=f"/api/farfield/{run_id}",  # D4 极坐标页联动
        warnings=warnings,
    )


def _smith_traces_from_touchstone(path: Path) -> tuple[list[dict[str, Any]], float]:
    """Touchstone → 各端口反射系数 S_ii 的 Smith 点列（网格几何单独给一次）。"""
    import numpy as np

    from rfauto.infra.visualization import smith_chart_data
    from rfauto.measurement.import_data import import_touchstone

    data = import_touchstone(path)
    net = data.network
    z0 = float(np.real(np.asarray(net.z0)[0, 0])) if np.asarray(net.z0).size else 50.0
    traces: list[dict[str, Any]] = []
    for i in range(net.nports):
        sm = smith_chart_data(data.freq_ghz, net.s[:, i, i], z0=z0, with_grid=False)
        traces.append({"file": path.name, "name": f"S{i + 1}{i + 1}", "port": i + 1, **sm})
    return traces, z0


def smith_view(run_id: str) -> dict[str, Any]:
    """单 run Smith 圆图数据（S 参数页增强）：各 Touchstone 的 S_ii 轨迹 + 网格。"""
    from rfauto.infra.visualization import smith_grid

    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:  # P9-13 路径段守卫（单源 safe_run_id）
        return error_envelope([f"非法 run_id: {run_id!r}"])
    run_dir = RUNS_DIR / run_id_clean
    results = run_dir / "results"
    if not results.is_dir():
        return error_envelope([f"该 run 无 results 产物: {run_id}"])
    traces: list[dict[str, Any]] = []
    z0 = 50.0
    warning = None
    try:
        files = [p for ext in (".s1p", ".s2p", ".s3p", ".s4p")
                 for p in sorted(results.glob(f"*{ext}"))]
        for sp in files:
            t, z0 = _smith_traces_from_touchstone(sp)
            traces.extend(t)
    except Exception as e:  # 解析失败不阻塞（同 sparams_series 惯例）
        warning = str(e)
    return ok_envelope(run_id=run_id, z0=z0, traces=traces,
                       grid=smith_grid(), warning=warning)


def smith_external(path: str) -> dict[str, Any]:
    """外部 Touchstone → Smith 轨迹（与 external_sparams 同构，只读）。"""
    from rfauto.infra.visualization import smith_grid

    p = Path(path)  # PathLike/字符串统一收敛（#140）
    if not p.is_file():
        return error_envelope([f"文件不存在: {p}"])
    if p.suffix.lower() not in (".s1p", ".s2p", ".s3p", ".s4p"):
        return error_envelope([f"非 Touchstone 文件: {p.name}（需 .s1p-.s4p）"])
    try:
        traces, z0 = _smith_traces_from_touchstone(p)
    except Exception as e:
        return error_envelope([f"Touchstone 解析失败: {e}"])
    return ok_envelope(path=str(p), file=p.name, z0=z0,
                       traces=traces, grid=smith_grid())


# ─── 优化洞察（E9 Pareto 前沿视图 / E10 可行性热图）─────────────────────────

def _load_run_trials(run_dir: Path) -> list[dict[str, Any]]:
    """读 run 的 trials/*.json 审计文件（F-14 已并入 _helpers 单源）。

    口径=``_helpers.load_run_trials``（按文件名排序、坏文件跳过、目录缺失
    返回空表，不按 trial_number 重排）——本消费面表序与原实现逐位一致
    （原实现即文件名序，无重排），调用点零改动。
    """
    return load_run_trials(run_dir)


def _run_dir_or_error(run_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:  # P9-13 路径段守卫（单源 safe_run_id）
        return None, error_envelope([f"非法 run_id: {run_id!r}"])
    run_dir = RUNS_DIR / run_id_clean
    if not run_dir.is_dir():
        return None, error_envelope([f"run 不存在: {run_id}"])
    return run_dir, None


def pareto_view(run_id: str) -> dict[str, Any]:
    """E9 Pareto 前沿视图（优化洞察页，只读）。

    双源（登记的"optimizer 有 pareto_points 但未接 UI"）：
    - results/pareto_front.json 存在（nsga2 run，E9 起落盘）→ 直读；
    - 缺产物（旧 run / TPE run）→ 从 trials/*.json 现算约束 Pareto：
      目标向量 = 逐 objective 违约量（与 run_multi_optimization 同口径，
      配方快照解析），约束违约量取 trial 审计的 constraint_values（无则
      视为无约束）；约束支配走 pareto_tools.constrained_pareto_front
      确定性内核。
    """
    run_dir, err = _run_dir_or_error(run_id)
    if err:
        return err
    front_path = run_dir / "results" / "pareto_front.json"
    if front_path.is_file():
        try:
            doc = json.loads(front_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return error_envelope([f"pareto_front.json 解析失败: {exc}"])
        return ok_envelope(run_id=run_id, source="pareto_front.json",
                           objective_names=doc.get("objective_names", []),
                           param_names=doc.get("param_names", []),
                           n_pareto=doc.get("n_pareto", len(doc.get("pareto_points", []))),
                           hv_convergence=doc.get("hv_convergence"),
                           constraint_names=doc.get("constraint_names", []),
                           points=doc.get("pareto_points", []))

    trials = _load_run_trials(run_dir)
    points = [t for t in trials
              if isinstance(t.get("params"), dict) and t.get("metrics")]
    if not points:
        return error_envelope([
            f"run {run_id} 无 pareto_front.json 且 trials 无可评估样本，"
            "前沿不可算（如实缺省，不凑绿 #122）"])
    snap = run_dir / "recipe.snapshot.yaml"
    if not snap.is_file():
        return error_envelope([
            f"run {run_id} 无配方快照，trials 目标向量无法重建"])
    import yaml

    try:
        recipe = yaml.safe_load(snap.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return error_envelope([f"配方快照解析失败: {exc}"])
    from rfauto.core.objectives import Objective
    from rfauto.optimization.optimizer import _single_objective_cost
    from rfauto.optimization.pareto_tools import constrained_pareto_front

    objectives = [Objective(**o) for o in recipe.get("objectives", [])]
    if len(objectives) < 2:
        return error_envelope([
            "配方 objectives 少于 2 个，无 Pareto 前沿语义（单目标 run 走成本曲线）"])
    obj_names = [o.metric for o in objectives]
    obj_mat: list[list[float]] = []
    viol_mat: list[list[float]] = []
    kept: list[dict[str, Any]] = []
    for t in points:
        metrics = t["metrics"]
        obj_mat.append([_single_objective_cost(metrics, o) for o in objectives])
        cv = t.get("constraint_values") or []
        viol_mat.append([float(v) for v in cv])
        kept.append(t)
    front_idx = constrained_pareto_front(obj_mat, viol_mat if any(viol_mat) else None)
    out_points: list[dict[str, Any]] = []
    for i in front_idx:
        t = kept[i]
        p: dict[str, Any] = {
            "params": t["params"],
            "objectives": {obj_names[j]: float(obj_mat[i][j])
                           for j in range(len(obj_names))},
            "cost": t.get("cost"),
        }
        if any(viol_mat):
            cv = viol_mat[i]
            p["constraint_values"] = cv
            p["feasible"] = all(v <= 0.0 for v in cv) if cv else None
        out_points.append(p)
    return ok_envelope(run_id=run_id, source="trials_recomputed",
                       objective_names=obj_names,
                       param_names=sorted({k for t in kept for k in t["params"]}),
                       n_pareto=len(out_points),
                       hv_convergence=None,
                       constraint_names=[c["metric"] for c in
                                         (recipe.get("optimization") or {}).get("constraints", [])
                                         if isinstance(c, dict) and c.get("metric")],
                       points=out_points,
                       n_trials_used=len(kept))


def feasibility_heatmap(
    run_id: str,
    x_param: str,
    y_param: str,
    grid_n: int = 12,
) -> dict[str, Any]:
    """E10 可行性热图（优化洞察页，只读）：trials 审计 → (x,y) 网格可行率。

    读 trials/*.json 的 params + constraint_values（optimizer.py 落盘口径，
    ≤0=可行），对 (x_param, y_param) 做**确定性分箱**（无插值无新依赖）：
    每格给点数 / 可行点数 / 可行率 / 平均总违约量。无约束 run（审计无
    constraint_values）如实报错不凑绿（#122）。
    """
    run_dir, err = _run_dir_or_error(run_id)
    if err:
        return err
    x_param = str(x_param)
    y_param = str(y_param)
    if x_param == y_param:
        return error_envelope(["x_param 与 y_param 不能相同"])
    grid_n = max(2, min(int(grid_n), 64))
    trials = _load_run_trials(run_dir)
    used: list[dict[str, Any]] = []
    total = len(trials)
    for t in trials:
        params = t.get("params")
        cv = t.get("constraint_values")
        if (isinstance(params, dict) and x_param in params and y_param in params
                and isinstance(cv, list) and len(cv) > 0):
            used.append(t)
    if not used:
        if total:
            return error_envelope([
                f"run {run_id} 的 {total} 条 trial 审计均无 (params, "
                "constraint_values) 记录：非约束 run 或旧 run 无 E10 审计，"
                "可行性热图不可算（如实缺省）"])
        return error_envelope([f"run {run_id} 无 trials 审计文件"])

    xs = [float(t["params"][x_param]) for t in used]
    ys = [float(t["params"][y_param]) for t in used]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    if x_hi <= x_lo or y_hi <= y_lo:
        return error_envelope([
            f"{x_param}/{y_param} 在已评样本中无展宽（单点或退化），"
            "热图网格不可分箱"])

    def _cell(v: float, lo: float, hi: float) -> int:
        # 确定性分箱：等宽格，右端点归末格（无浮点边界抖动逃逸）
        idx = int((v - lo) / (hi - lo) * grid_n)
        return min(max(idx, 0), grid_n - 1)

    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for t in used:
        ci = (_cell(float(t["params"][x_param]), x_lo, x_hi),
              _cell(float(t["params"][y_param]), y_lo, y_hi))
        cv = [float(v) for v in t["constraint_values"]]
        feasible = all(v <= 0.0 for v in cv)
        total_viol = sum(max(0.0, v) for v in cv)
        c = cells.setdefault(ci, {"n": 0, "n_feasible": 0, "violation_sum": 0.0})
        c["n"] += 1
        c["n_feasible"] += int(feasible)
        c["violation_sum"] += total_viol
    out_cells: list[dict[str, Any]] = []
    for (i, j) in sorted(cells):
        c = cells[(i, j)]
        out_cells.append({
            "i": i, "j": j, "n": c["n"], "n_feasible": c["n_feasible"],
            "feasible_rate": round(c["n_feasible"] / c["n"], 6),
            "mean_total_violation": round(c["violation_sum"] / c["n"], 6),
        })
    n_feasible_total = sum(1 for t in used
                           if all(float(v) <= 0.0 for v in t["constraint_values"]))
    return ok_envelope(run_id=run_id,
                       x_param=x_param, y_param=y_param, grid_n=grid_n,
                       x_edges=[round(x_lo + (x_hi - x_lo) * k / grid_n, 9)
                                for k in range(grid_n + 1)],
                       y_edges=[round(y_lo + (y_hi - y_lo) * k / grid_n, 9)
                                for k in range(grid_n + 1)],
                       cells=out_cells,
                       n_trials_used=len(used), n_trials_total=total,
                       n_feasible_total=n_feasible_total)


# ── 数据集 / 标定锚 / UQ 三页（UI 大块批，全部只读消费既有服务面）───────


def datasets_overview() -> dict[str, Any]:
    """数据集页清单（只读）：runs/datasets 注册表逐数据集关键数字。

    数据源 = dataset_insights.list_datasets（行数/点数/可见性/GT/时间）；
    models（模板族）best-effort 从 manifest 提取（workdir ingest 的
    ``per_family_rows`` 或 materialize 的 ``ground_truth.per_model`` 键集），
    两键皆缺（旧 manifest）时为空列表——前端如实显示"未登记"，不臆测。
    """
    from rfauto.service.dataset_insights import list_datasets
    from rfauto.service.dataset_service import MANIFEST_NAME

    base = list_datasets()
    if not base.get("ok"):
        return base
    items: list[dict[str, Any]] = []
    for ds in base["datasets"]:
        models: list[str] = []
        try:
            import yaml

            manifest = yaml.safe_load(
                (Path(ds["dataset_dir"]) / MANIFEST_NAME).read_text(
                    encoding="utf-8"))
            if isinstance(manifest, dict):
                per_family = manifest.get("per_family_rows")
                gt = manifest.get("ground_truth")
                per_model = gt.get("per_model") if isinstance(gt, dict) else None
                src = (per_family if isinstance(per_family, dict) and per_family
                       else (per_model if isinstance(per_model, dict)
                             and per_model else {}))
                models = sorted(str(k) for k in src)
        except Exception:  # 观测面 best-effort（#105），不阻塞清单
            models = []
        items.append(dict(ds, models=models))
    return ok_envelope(out_dir=base["out_dir"],
                       datasets=items, n_datasets=len(items))


def dataset_preview(
    name: str,
    limit: int = 20,
    model: str | None = None,
) -> dict[str, Any]:
    """数据集页行级预览（只读）：query_dataset 抽样 N 行 + 列清单。

    返回即 query_dataset 原契约（{ok, rows, n_rows, columns, ...}）；
    ``n_rows`` 是抽样返回行数不是全量计数（#369），前端如实标注。
    """
    from rfauto.service.dataset_service import query_dataset

    try:
        limit_i = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        return error_envelope([f"limit 非法: {limit!r}"])
    return query_dataset(name, limit=limit_i, model=model or None)


def anchors_overview(path: str | None = None) -> dict[str, Any]:
    """标定锚页清单（只读）：list_anchors 摘要 + stale 报告按 anchor_id 合并。

    逐锚附 ``stale_info``（anchors_stale_report 行：age_days/stale/
    date_kind）；``stale=None``（无 last_verified）原样透传——前端
    如实渲染 UNKNOWN，不虚构判定。
    """
    from rfauto.service import anchors_service

    lst = anchors_service.list_anchors(path)
    if not lst.get("ok"):
        return lst
    stale = anchors_service.anchors_stale_report(path=path)
    stale_by_id = {r["anchor_id"]: r for r in stale.get("anchors", [])}
    anchors = [dict(a, stale_info=stale_by_id.get(str(a.get("anchor_id"))))
               for a in lst.get("anchors", [])]
    return ok_envelope(registry=lst.get("registry"),
                       count=lst.get("count", 0),
                       expected_count=lst.get("expected_count", 0),
                       load_errors=list(lst.get("load_errors") or []),
                       stale_count=stale.get("stale_count", 0),
                       no_date_count=stale.get("no_date_count", 0),
                       anchors=anchors)


def anchor_detail(anchor_id: str, path: str | None = None) -> dict[str, Any]:
    """标定锚页单锚详情（只读）：inspect_anchor 透传（raw 全量记录）。"""
    from rfauto.service import anchors_service

    return anchors_service.inspect_anchor(anchor_id, path)


#: UQ 样本集扫描的单文件解析上限（字节）：超过则入清单但不解析内容
#: （n_samples=None），不静默吞资产也不把大文件整读进内存。
_UQ_SAMPLE_PARSE_CAP_BYTES = 5 * 1024 * 1024

#: UQ 样本集扫描的最大目录深度（runs/<run>/calibration/samples.json 为 2 层）。
_UQ_SAMPLE_MAX_DEPTH = 3


def uq_samples_list(limit: int = 200) -> dict[str, Any]:
    """UQ 页输入资产清单（只读）：runs/ 下校准样本集（samples.json 族）扫描。

    判据（uq_service._load_yield_context 消费口径）：文件名含 ``samples``
    且 .json 结尾、顶层 JSON 为对象且含非空 ``samples`` 列表。深度受限
    best-effort 扫描；损坏/超大小上限的文件如实带 ``parsed=False`` 入清单
    （n_samples=None）；解析成功但 samples 为空/缺失的同名文件视作非资产
    不入清单。绝不 mock。
    """
    import os

    root = RUNS_DIR
    items: list[dict[str, Any]] = []
    if root.is_dir():
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            if depth >= _UQ_SAMPLE_MAX_DEPTH:
                dirnames[:] = []
            for fn in filenames:
                if "samples" not in fn or not fn.endswith(".json"):
                    continue
                p = Path(dirpath) / fn
                try:
                    size = p.stat().st_size
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                n_samples: int | None = None
                bounds_params: list[str] = []
                n_objectives: int | None = None
                parsed = False
                listed = True
                if size <= _UQ_SAMPLE_PARSE_CAP_BYTES:
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                        samples = data.get("samples") if isinstance(data, dict) else None
                        if isinstance(samples, list) and samples:
                            parsed = True
                            n_samples = len(samples)
                            bounds = data.get("bounds")
                            if isinstance(bounds, dict):
                                bounds_params = sorted(str(k) for k in bounds)
                            objs = data.get("objectives")
                            n_objectives = len(objs) if isinstance(objs, list) else None
                        else:
                            # 解析成功但无非空 samples 列表：非 UQ 资产，
                            # 不入清单（与同名巧合文件同等对待）
                            listed = False
                    except Exception:
                        parsed = False  # 损坏：如实入清单不解析
                if not listed:
                    continue
                items.append({
                    "path": p.as_posix(),
                    "size_bytes": size,
                    "mtime": mtime,
                    "parsed": parsed,
                    "n_samples": n_samples,
                    "n_objectives": n_objectives,
                    "bounds_params": bounds_params,
                })
                if len(items) >= max(1, int(limit)):
                    return ok_envelope(samples_root=root.as_posix(),
                                       items=items, n_items=len(items),
                                       truncated=True)
    items.sort(key=lambda it: (-it["mtime"], it["path"]))
    return ok_envelope(samples_root=root.as_posix(),
                       items=items, n_items=len(items), truncated=False)


def uq_yield_run(
    samples_path: str,
    tolerances: dict[str, float] | None = None,
    *,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """UQ 页运行面：直接透传 uq_service.surrogate_yield（确定性内核）。

    规则 7：数值全部由内核产出，本函数零计算零 mock；输入形参校验
    （σ 必须可 float）在本边界完成，语义校验/缺失容忍由内核 errors
    如实返回。返回契约见 surrogate_yield（yield_rate/metric_stats/
    sensitivity_ranking/sensitivity_violation_delta）。
    """
    from rfauto.service.uq_service import surrogate_yield

    tol: dict[str, float] = {}
    for k, v in (tolerances or {}).items():
        try:
            tol[str(k)] = float(v)  # 显式拒收不可转 float 的 σ（bool 亦然）
        except (TypeError, ValueError):
            return error_envelope([f"公差 σ 必须是数值: {k}={v!r}"])
    return surrogate_yield(samples_path, tol, n=int(n), seed=int(seed),
                           kind=str(kind))
