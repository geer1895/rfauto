"""M3 谷区定向加密采集（M3 第一批）。

判据/口径全部预声明 runs/datafactory_m3/criteria.md（写死再跑）。
承接 M2/M4 独立同因归因：S11 深谷区
（w≈0.9055-0.9103）亚栅格锐度 → 谷区定向加密 30 点（谷区 LHS 20 + 谷芯
均匀 10）。采集链复用 factory_m1_collect（只 import 不改源）：
write_run_products / compute_point_metrics(port_beta_csv=) /
beta_metrics_from_port_beta / w_fingerprint / existing_mline_w。

用法（cwd=仓库根）：
  python scripts/factory_m3_valley.py --plan         # 采样计划落盘（不可变）
  python scripts/factory_m3_valley.py --audit        # 渲染审计 2 谷芯端点（离线）
  python scripts/factory_m3_valley.py --benchmark    # 合成非退化前置门（离线）
  python scripts/factory_m3_valley.py --collect      # 真机批量（共享锁内；resume）
  python scripts/factory_m3_valley.py --materialize  # 物化+批内判读+快检（离线）

纪律（criteria.md 逐条预声明）：
- 共享锁 runs/.oe_collect.lock（O_CREAT|O_EXCL 原子建、60s 轮询、finally
  删、pid 陈锁核验接管）——锁内= #261 命令行查 + 全部真跑 + 产物落盘。
- 放量前首点 ingest 探针 1 行成行（#251④）；QuotaGuard(30, 1.0h)；
  断点 resume（plan.json 不可变 + points_index 逐点落盘）。
- provenance：import 后覆盖 factory_m1_collect.STUDY="datafactory_m3" +
  写后 patch meta.source/recipe notes——判别字段（adapter/study）不为 M1
  污染（#144）；数值判缺一律 is not None（#364④）。

退出码：--collect/--benchmark/--audit/--materialize 0=门过；1=门未达/执行
失败；2=参数错误。
"""

from __future__ import annotations

import argparse
import contextlib
import itertools
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 采集链复用（只 import 不改源）：m1 模块导入时自注入 src 路径，
# 脚本目录经 python 运行/测试 sys.path 注入解析（本文件 cwd 守卫=仓库根）。
import factory_m1_collect as m1
from factory_m1_collect import (
    beta_metrics_from_port_beta,  # noqa: F401  re-export 供单测钉契约
    compute_point_metrics,
    existing_mline_w,
    w_fingerprint,
    write_run_products,
)

# ─── 预声明常量（criteria.md 同源，改门先改 criteria 再改这里） ────────────────
REPO = Path(__file__).resolve().parents[1]
TEMPLATE = "mline"
SUBSTRATE = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # rogers4350b 锚口径
FREQ_RANGE_GHZ = (2.0, 3.0)
LINE_LEN_MM = 40.0
V_LOW, V_HIGH = 0.70, 1.00          # 谷区 LHS 域
N_LHS = 20
CORE_LO, CORE_HI = 0.900, 0.920     # 谷芯均匀域
N_CORE = 10
LHS_SEED = 20260920
LHS_POOL = 40
LHS_MAX_POOLS = 5
NUDGE_MM = 1e-5                      # 谷芯撞点重采样步长（10nm=指纹单元 10 倍）
STUDY = "datafactory_m3"
SOLVE_TIMEOUT_S = 900.0
QUOTA_TRIALS = 30
QUOTA_WALL_H = 1.0
MEDIAN_WALL_GATE_S = 90.0            # 30×~90s 预算带
N_ROWS_TARGET = 30
BUDGET_WALL_S = 45.0 * 60.0          # 目标预算
PARTIAL_FACTOR = 1.5                 # 超 1.5× → PARTIAL(超预算)（67.5min）
M1_DATASET = "datafactory_m1_mline_20260919"
DATASET_NAME = "datafactory_m3_valley_20260920"
PROBE_DATASET = "datafactory_m3_ingest_probe"
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
ROOT = REPO / "runs" / "datafactory_m3"
PLAN_PATH = ROOT / "plan.json"
INDEX_PATH = ROOT / "points_index.json"
JUDGMENT_PATH = ROOT / "judgment.json"
AUDIT_PATH = ROOT / "render_audit.json"
BENCH_PATH = ROOT / "precondition_benchmark.json"
LOCK_POLL_S = 60.0

AUDIT_W = (CORE_LO, CORE_HI)         # PG1 谷芯端点

__all__ = [
    "build_valley_plan",
    "core_grid_points",
    "judge_batch",
    "nudge_free",
    "w_fingerprint",
]


# ─── 纯逻辑（单测钉死面，零引擎零 IO） ────────────────────────────────────────

def core_grid_points(lo: float = CORE_LO, hi: float = CORE_HI,
                     n: int = N_CORE) -> list[float]:
    """谷芯均匀网格（含端点，步距 (hi-lo)/(n-1)≈2.2222µm）。"""
    return [lo + i * (hi - lo) / (n - 1) for i in range(n)]


def nudge_free(w: float, taken: set[int], step: float = NUDGE_MM,
               max_iter: int = 1000) -> tuple[float, int]:
    """撞点重采样：w += step 至指纹空闲（确定性单调，步长=指纹单元 10 倍）。

    返回 (新 w, 步进次数)；超 max_iter 抛 ValueError（计划拒绝生成，不静默）。
    """
    x = float(w)
    for i in range(1, max_iter + 1):
        x += float(step)
        if w_fingerprint(x) not in taken:
            return x, i
    raise ValueError(f"nudge_free 超限: w={w} taken={len(taken)}")


def _point_id(w: float, used: set[str]) -> str:
    """点 id（m3_w<µm 四位>）；四舍五入撞名时追加序号守卫（M1 同法）。"""
    base = f"m3_w{round(float(w) * 1000):04d}"
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"


def build_valley_plan(dedup_w: list[float]) -> dict[str, Any]:
    """采样计划（纯函数，恰 30 点）：谷芯均匀 10 + 谷区 LHS 20。

    查重键 = w_fingerprint 对 M1 库存 ∪ 批内已收点；LHS 撞点池重采样
    （seed+1 续抽至多 LHS_MAX_POOLS 轮）；谷芯撞点 nudge_free 定值重采样。
    点序：谷芯（w 升序）在前、LHS（w 升序）在后（stable、resume 幂等）。
    """
    from rfauto.optimization.sample_design import lhs_points

    taken = {w_fingerprint(w) for w in dedup_w}
    n_dedup_existing = len(taken)
    n_core_nudged = 0
    n_lhs_dropped = 0

    core: list[float] = []
    for w in core_grid_points():
        if w_fingerprint(w) in taken:
            w, _n = nudge_free(w, taken)
            n_core_nudged += 1
        taken.add(w_fingerprint(w))
        core.append(w)

    lhs: list[float] = []
    pool_seed = LHS_SEED
    for _pool_i in range(LHS_MAX_POOLS):
        res = lhs_points({"w_mm": (V_LOW, V_HIGH)}, LHS_POOL, seed=pool_seed)
        pool_seed += 1
        for pt in res["points"]:
            w = float(pt["w_mm"])
            if w_fingerprint(w) in taken:
                n_lhs_dropped += 1
                continue
            taken.add(w_fingerprint(w))
            lhs.append(w)
            if len(lhs) >= N_LHS:
                break
        if len(lhs) >= N_LHS:
            break
    lhs = lhs[:N_LHS]

    used: set[str] = set()
    points: list[dict[str, Any]] = []
    for w in sorted(core) + sorted(lhs):
        pid = _point_id(w, used)
        used.add(pid)
        points.append({"point_id": pid, "w_mm": w, "line_len_mm": LINE_LEN_MM,
                       "kind": "core" if len(points) < N_CORE else "lhs"})
    return {
        "points": points,
        "stats": {
            "n_core": len(core),
            "n_lhs_requested": N_LHS,
            "n_lhs_kept": len(lhs),
            "n_core_nudged": n_core_nudged,
            "n_lhs_dropped": n_lhs_dropped,
            "n_plan_total": len(points),
            "lhs_seed": LHS_SEED,
            "lhs_pool": LHS_POOL,
            "lhs_max_pools": LHS_MAX_POOLS,
            "dedup_source": M1_DATASET,
            "dedup_n_existing_w": n_dedup_existing,
            "core_step_um": round((CORE_HI - CORE_LO) / (N_CORE - 1) * 1000, 4),
        },
    }


def judge_batch(
    attempted: int,
    n_rows: int,
    walls_s: list[float],
    median_gate_s: float = MEDIAN_WALL_GATE_S,
    n_rows_target: int = N_ROWS_TARGET,
) -> dict[str, Any]:
    """批内三门判定（纯函数；criteria 批内三门，FAIL 如实不凑绿）。"""
    row_rate = (float(n_rows) / attempted) if attempted > 0 else 0.0
    med = float(statistics.median(walls_s)) if walls_s else None
    g1 = attempted > 0 and n_rows == attempted
    g2 = med is not None and med <= float(median_gate_s)
    g3 = n_rows == int(n_rows_target)
    gates = {
        "G1_row_rate_100pct": {
            "pass": bool(g1), "n_attempted": attempted, "n_rows": n_rows,
            "row_rate": round(row_rate, 6)},
        "G2_median_wall_le_90s": {
            "pass": bool(g2), "median_wall_s": None if med is None else round(med, 2),
            "n_points": len(walls_s), "gate_s": float(median_gate_s)},
        "G3_rows_eq_30": {
            "pass": bool(g3), "n_rows": n_rows, "gate": int(n_rows_target)},
    }
    passed = bool(g1 and g2 and g3)
    fails = [k for k, g in gates.items() if not g["pass"]]
    verdict = "PASS" if passed else f"FAIL: {'; '.join(fails)}"
    return {"pass": passed, "verdict": verdict, "gates": gates}


def core_min_spacing_um(ws: list[float]) -> float | None:
    """谷芯点实测最小成对间距（µm；None=不足 2 点）。"""
    core = sorted(w for w in ws if CORE_LO - 1e-9 <= w <= CORE_HI + 1e-9)
    if len(core) < 2:
        return None
    return round(min(b - a for a, b in itertools.pairwise(core)) * 1000.0, 4)


# ─── 共享锁（与并行 M4 谷芯复跑任务互斥；criteria 互斥节） ────────────────────

def _pid_alive(pid: int) -> bool | None:
    """pid 存活性（tasklist 只读查询；探测失败返回 None=按存活处理，#105）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True, timeout=30)
        return str(pid) in (out.stdout or "")
    except Exception:
        return None


def acquire_lock(task: str, poll_s: float = LOCK_POLL_S) -> None:
    """O_CREAT|O_EXCL 原子建锁；占用则 60s 轮询并打印等待日志（criteria）。"""
    import os

    while True:
        try:
            fd = os.open(str(LOCK_PATH),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"task": task,
                       "ts": datetime.now(timezone.utc).isoformat(),
                       "pid": os.getpid()}
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            os.close(fd)
            return
        except FileExistsError:
            holder: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                holder = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            pid = holder.get("pid")
            alive = _pid_alive(pid) if isinstance(pid, int) else None
            if alive is False:
                print(f"[m3] 陈锁接管（持有者 pid={pid} 已死）：{holder}")
                with contextlib.suppress(OSError):
                    LOCK_PATH.unlink()
                continue
            print(f"[m3] 锁被占（{holder or '未知持有者'}），{poll_s:.0f}s 后重试…",
                  flush=True)
            time.sleep(poll_s)


def release_lock(owner_pid: int) -> None:
    """删锁（删前校验内容 pid=自身，防误删后到者锁；best-effort #105）。"""
    try:
        holder = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        if holder.get("pid") == owner_pid:
            LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def oe_foreign_running() -> list[str]:
    """#261 互斥查：python 进程 CommandLine 含 _rfauto_runner|simulation.py。

    临时 .ps1 经 powershell -NoProfile -ExecutionPolicy Bypass -File 执行
    （#289：内联 $_ 会被 shell 层展开/引号嵌套不可过）。探测失败=如实抛错
    （fail-closed：查不了就不起跑）。
    """
    ROOT.mkdir(parents=True, exist_ok=True)
    ps1 = ROOT / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match '_rfauto_runner|simulation\\.py' } | "
        "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        ps1.unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(f"#261 进程查询失败 rc={out.returncode}: {out.stderr[:300]}")
    return [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]


# ─── 离线面（锁外）：渲染审计 / 合成裁判 ─────────────────────────────────────

def render_audit_point(w_mm: float) -> dict[str, Any]:
    """PG1 单点审计：render_script（mesh 0=与求解同参 #368）→ exec 网格段。

    判据（criteria PG1）：渲染+exec 无守卫抛错；金属原语存在且迹线 x 向
    宽=设计 w（±1e-6 mm）；全轴网格最小线距如实记录（信息项非门）。
    """
    from rfauto.adapters.openems_templates import render_script

    text = render_script(
        TEMPLATE, {"w_mm": float(w_mm), "line_len_mm": LINE_LEN_MM},
        FREQ_RANGE_GHZ, mesh_resolution_mm=0.0, substrate=dict(SUBSTRATE))
    cut = text.index("FDTD.Run(")
    scope: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(REPO / "_factory_m3_render_audit.py"),
    }
    exec(compile(text[:cut], "factory_m3_render_audit", "exec"), scope)
    csx = scope.get("CSX")
    if csx is None:
        raise RuntimeError("exec 后无 CSX 对象")
    import numpy as np

    metal_boxes: list[tuple[Any, Any]] = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        if str(prop.GetTypeString()) != "Metal":
            continue
        for prim in prop.GetAllPrimitives():
            if hasattr(prim, "GetStart"):
                s = np.asarray(prim.GetStart(), dtype=float)
                e = np.asarray(prim.GetStop(), dtype=float)
                lo, hi = np.minimum(s, e), np.maximum(s, e)
            else:
                bb = np.asarray(prim.GetBoundBox(), dtype=float)
                lo, hi = bb[0], bb[1]
            metal_boxes.append((lo, hi))
    if not metal_boxes:
        raise RuntimeError("无金属原语（渲染段未画导体？）")
    # 迹线原语：金属中 x 向宽度最接近设计 w 者
    trace = min(metal_boxes,
                key=lambda p: abs(float(p[1][0] - p[0][0]) - w_mm * 1e-3))
    w_meas_mm = float(trace[1][0] - trace[0][0]) * 1e3
    if abs(w_meas_mm - float(w_mm)) > 1e-6:
        raise RuntimeError(
            f"迹线 x 宽 {w_meas_mm:.9f}mm ≠ 设计 {w_mm:.6f}mm（参数未驱动几何？）")
    mesh_lines = {}
    mesh_min = {}
    for axis in ("x", "y", "z"):
        try:
            import numpy as np

            lines = np.asarray(scope["mesh"].GetLines(axis), dtype=float)
        except Exception as exc:  # 网格对象缺失=审计失败面
            raise RuntimeError(f"mesh.GetLines({axis}) 失败: {exc!r}") from exc
        if lines.size < 2:
            raise RuntimeError(f"{axis} 向网格线不足")
        d = np.diff(np.sort(lines))
        mesh_lines[axis] = int(lines.size)
        mesh_min[axis] = float(d.min())
    return {
        "w_mm": float(w_mm),
        "ok": True,
        "n_metal_prims": len(metal_boxes),
        "trace_w_meas_mm": round(w_meas_mm, 9),
        "mesh_n_lines": mesh_lines,
        "mesh_min_spacing_m": {k: float(f"{v:.6g}") for k, v in mesh_min.items()},
        "note": "渲染成功+无守卫抛错+参数驱动几何（#212/#368 同参 mesh 0 档）；"
                "采样间距≠网格线距，#152/#349 不适用于 w 向采样间距",
    }


def run_audit() -> int:
    """PG1 渲染审计（离线，锁外；写 render_audit.json）。"""
    recs = []
    ok = True
    for w in AUDIT_W:
        try:
            rec = render_audit_point(w)
        except Exception as exc:
            rec = {"w_mm": float(w), "ok": False, "error": repr(exc)}
            ok = False
        recs.append(rec)
        print(f"[m3] PG1 w={w:.6f}: ok={rec['ok']}"
              + ("" if rec["ok"] else f" error={rec.get('error')}"))
    payload = {"gate": "PG1_render_audit", "pass": ok, "points": recs,
               "ts": datetime.now(timezone.utc).isoformat()}
    ROOT.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[m3] PG1 判定: {'PASS' if ok else 'FAIL'} → {AUDIT_PATH}")
    return 0 if ok else 1


def run_benchmark() -> int:
    """PG0 合成非退化门（离线，锁外；写 precondition_benchmark.json）。"""
    from rfauto.service.active_learning import convergence_speedup_benchmark

    t0 = time.time()
    res = convergence_speedup_benchmark()
    res["gate"] = "PG0_convergence_speedup"
    res["pass"] = bool(res.get("passes_30pct"))  # is not None 显式化（#364④）
    res["wall_s"] = round(time.time() - t0, 1)
    ROOT.mkdir(parents=True, exist_ok=True)
    BENCH_PATH.write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[m3] PG0 speedup_median={res.get('speedup_median')} "
          f"pass={res['pass']} wall={res['wall_s']}s → {BENCH_PATH}")
    return 0 if res["pass"] else 1


# ─── 真机采集（锁内）与物化判读（锁外） ───────────────────────────────────────

def _load_or_build_plan() -> tuple[dict[str, Any], list[str]]:
    """计划不可变（首次生成后 resume 同计划）；返回 (plan, dedup_errs)。"""
    dedup_w, errs = existing_mline_w(M1_DATASET)
    if PLAN_PATH.exists():
        return json.loads(PLAN_PATH.read_text(encoding="utf-8")), errs
    plan = build_valley_plan(dedup_w)
    ROOT.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan, errs


def _load_index() -> dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def _save_index(index: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def done_run_ids(index: dict[str, Any]) -> list[str]:
    return [row["rid"] for _pid, row in sorted(index.items())
            if isinstance(row, dict) and row.get("status") == "done"]


def _patch_provenance(run_dir: Path) -> None:
    """写后 provenance 修正（criteria 落盘节）：meta.source/notes + recipe notes。

    study 字段已在 write_run_products 内经 m1.STUDY 覆盖为 datafactory_m3；
    此处只修写死的 M1 字面残留（meta.source、criteria 引用、notes 文本）。
    """
    meta_p = run_dir / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["source"] = "datafactory_m3_valley"
    meta["criteria"] = "runs/datafactory_m3/criteria.md"
    meta_p.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    rec_p = run_dir / "recipe.snapshot.yaml"
    text = rec_p.read_text(encoding="utf-8")
    text = (text
            .replace("datafactory_m1 采集点", "datafactory_m3 谷区加密采集点")
            .replace("runs/data_factory_m1/criteria.md", "runs/datafactory_m3/criteria.md"))
    rec_p.write_text(text, encoding="utf-8")


def _port_beta_csv(evals_root: Path, t_solve_start: float) -> Path | None:
    """solve 起点后 mtime 最新的 eval_* 目录里的 port_beta.csv（防串味）。"""
    cands = []
    for d in evals_root.glob("eval_*"):
        mt = d.stat().st_mtime
        if mt >= t_solve_start - 2.0:
            cands.append((mt, d))
    if not cands:
        return None
    latest = max(cands, key=lambda t: t[0])[1]
    p = latest / "port_beta.csv"
    return p if p.exists() else None


def run_collect(repo_root: Path) -> int:
    """真机批量采集（共享锁内整段；断点 resume 幂等）。"""
    if str(Path.cwd().resolve()) != str(repo_root.resolve()):
        print(f"[m3] 拒跑：cwd 必须是仓库根 {repo_root}（当前 {Path.cwd()}）")
        return 2
    from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir
    from rfauto.pipeline.quota_guard import QuotaExceededError, QuotaGuard, QuotaLimits
    from rfauto.service.dataset_service import materialize_dataset

    plan, dedup_errs = _load_or_build_plan()
    index = _load_index()
    print(f"[m3] plan={plan['stats']['n_plan_total']} 点 "
          f"(谷芯 {plan['stats']['n_core']} + LHS {plan['stats']['n_lhs_kept']}，"
          f"LHS 撞点剔除 {plan['stats']['n_lhs_dropped']}、谷芯重采样 "
          f"{plan['stats']['n_core_nudged']}；对 M1 库存 "
          f"{plan['stats']['dedup_n_existing_w']} w 查重；"
          f"缓存态 {m1.os_cache_state()})")
    for e in dedup_errs[:5]:
        print(f"[m3][warn] {e}")

    # provenance：STUDY 覆盖（recipe.study / meta.study_name 随 write 生效）
    m1.STUDY = STUDY

    evals_root = ROOT / "evals"
    adapter = OpenEMSOptAdapter(
        FREQ_RANGE_GHZ, template=TEMPLATE, substrate=SUBSTRATE,
        solve_timeout_s=SOLVE_TIMEOUT_S, work_root=evals_root)
    guard = QuotaGuard(QuotaLimits(max_trials=QUOTA_TRIALS, max_wall_hours=QUOTA_WALL_H))
    import os as _os

    owner_pid = _os.getpid()
    acquire_lock("factory_m3_valley")
    t0 = time.time()
    walls: list[float] = []
    ingest_checked = False
    partial = False
    try:
        foreign = oe_foreign_running()
        if foreign:
            print("[m3] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：\n"
                  + "\n".join(f"  {ln}" for ln in foreign[:10]))
            return 1
        print("[m3] #261 命令行查：无他轨 OE 进程，锁内起跑")
        for pt in plan["points"]:
            pid = str(pt["point_id"])
            row = index.get(pid)
            if isinstance(row, dict) and row.get("status") == "done":
                walls.append(float(row["wall_s"]))
                continue
            guard.check_trial(len(walls))
            guard.check_wall_time(t0)
            w = float(pt["w_mm"])
            rid = generate_run_id()
            run_dir = create_run_dir(repo_root, rid)
            adapter.set_variables({"w_mm": w, "line_len_mm": LINE_LEN_MM})
            t_solve_wall = time.time()       # 墙钟（对 eval 目录 mtime 归属）
            t_solve_mono = time.monotonic()  # 单调钟（墙钟时长）
            rep = adapter.solve(timeout_s=SOLVE_TIMEOUT_S)
            solve_wall = time.monotonic() - t_solve_mono
            if not rep.success:
                index[pid] = {"status": "failed", "rid": rid,
                              "msg": str(rep.message)[:300]}
                _save_index(index)
                print(f"[m3] {pid} FAIL solve: {rep.message}")
                continue
            net = adapter.get_sparams()
            beta_csv = _port_beta_csv(evals_root, t_solve_wall)
            metrics, notes = compute_point_metrics(net, port_beta_csv=beta_csv)
            write_run_products(run_dir, w, net, solve_wall,
                               str(adapter.eval_root), metrics, notes,
                               line_len_mm=LINE_LEN_MM)
            _patch_provenance(run_dir)
            index[pid] = {"status": "done", "rid": rid, "w_mm": w,
                          "kind": str(pt.get("kind", "")),
                          "wall_s": round(solve_wall, 2)}
            _save_index(index)
            walls.append(solve_wall)
            eps = metrics.get("eps_eff_beta_mean_in_band")
            print(f"[m3] {pid} rid={rid} wall={solve_wall:.1f}s "
                  f"s11_min={metrics.get('s11_db_min_in_band')}dB "
                  f"eps_beta={eps if eps is not None else 'skipped'}", flush=True)
            # 放量纪律（#251④）：首点 ingest 核对成行才继续批量
            if not ingest_checked:
                probe = materialize_dataset(
                    run_ids=[rid], name=PROBE_DATASET, health_gate=True)
                n_probe = int(probe.get("n_rows") or 0)
                if not probe.get("ok") or n_probe != 1:
                    print(f"[m3] 首点 ingest 核对失败（ok={probe.get('ok')} "
                          f"n_rows={n_probe} errors={probe.get('errors')} "
                          f"unhealthy={probe.get('unhealthy_runs')}）——停批排查")
                    return 1
                print("[m3] 首点 ingest 核对 OK（1 行成行，health gate 不拦）")
                ingest_checked = True
    except QuotaExceededError as exc:
        partial = True
        print(f"[m3] quota 停批（PARTIAL 判定，已完成点照常入库）: {exc}")
    finally:
        release_lock(owner_pid)

    return _finalize(index, plan, walls, partial, t0)


def _finalize(index: dict[str, Any], plan: dict[str, Any], walls: list[float],
              partial: bool, t0: float, measure_budget: bool = True) -> int:
    """物化+三门判读+快检（锁外离线面；幂等）。

    measure_budget=False（--materialize 幂等重跑入口）时预算态按
    "recomputed(见 collect 批次 judgment)" 记，不用本次 0 墙钟误标。
    """
    from rfauto.service.dataset_service import materialize_dataset, query_dataset

    rids = done_run_ids(index)
    n_done = len(rids)
    n_failed = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "failed")
    attempted = n_done + n_failed
    batch_wall = time.time() - t0
    print(f"[m3] 批量墙钟 {batch_wall:.0f}s；done={n_done} failed={n_failed}")

    judgment: dict[str, Any] = {}
    n_unhealthy = n_skipped = 0
    n_rows = -1
    if rids:
        mat = materialize_dataset(run_ids=rids, name=DATASET_NAME, health_gate=True)
        if mat.get("ok"):
            n_rows = int(mat.get("n_rows") or 0)
            n_unhealthy = len(mat.get("unhealthy_runs") or [])
            n_skipped = len(mat.get("skipped_runs") or [])
            print(f"[m3] 物化 ok rows={n_rows} unhealthy={n_unhealthy} "
                  f"skipped={n_skipped} dup={mat.get('n_dup')}")
        else:
            print(f"[m3] 物化失败: {mat.get('errors')}")
    else:
        print("[m3] 无 done 点可物化")

    judgment = judge_batch(attempted, max(n_rows, 0), walls)
    # 预算态（criteria：≤45min 目标 / >1.5× PARTIAL / 中间=超目标注记）
    if not measure_budget:
        budget_status = "recomputed(见 --collect 批次 judgment)"
    else:
        over_factor = batch_wall / BUDGET_WALL_S
        if batch_wall > BUDGET_WALL_S * PARTIAL_FACTOR:
            partial = True
            budget_status = f"PARTIAL(超预算 {over_factor:.2f}×)"
        elif batch_wall > BUDGET_WALL_S:
            budget_status = f"over_target({over_factor:.2f}×, <{PARTIAL_FACTOR}× 仍 PASS)"
        else:
            budget_status = f"within_target({over_factor:.2f}×)"
    if partial:
        judgment["verdict"] = f"PARTIAL(超预算): {judgment['verdict']}"

    # 批后快检（记录非门）：β 列覆盖 / eps_beta 范围 / 谷芯最小间距
    beta_ratio = None
    eps_beta: list[float] = []
    if rids:
        q = query_dataset(DATASET_NAME, model="mline",
                          columns=["metrics_json"], limit=100000)
        rows = q.get("rows") or [] if q.get("ok") else []
        n_beta = 0
        for r in rows:
            try:
                mt = json.loads(str(r.get("metrics_json") or "{}"))
            except (ValueError, TypeError):
                mt = {}
            if isinstance(mt, dict) and mt.get("eps_eff_beta_mean_in_band") is not None:
                n_beta += 1
                eps_beta.append(float(mt["eps_eff_beta_mean_in_band"]))
        if rows:
            beta_ratio = round(n_beta / len(rows), 4)
    core_ws = [float(r["w_mm"]) for r in index.values()
               if isinstance(r, dict) and r.get("status") == "done"
               and r.get("kind") == "core"]
    quickcheck = {
        "beta_col_ratio": beta_ratio,
        "eps_eff_beta_min": min(eps_beta) if eps_beta else None,
        "eps_eff_beta_max": max(eps_beta) if eps_beta else None,
        "core_min_spacing_um": core_min_spacing_um(core_ws),
        "n_core_collected": len(core_ws),
    }

    judgment["partial_budget"] = partial
    judgment["meta"] = {
        "plan": plan["stats"], "n_failed": n_failed,
        "dataset": DATASET_NAME, "n_rows": max(n_rows, 0),
        "quota": {"trials": QUOTA_TRIALS, "wall_hours": QUOTA_WALL_H},
        "batch_wall_s": round(batch_wall, 1),
        "budget_status": budget_status,
        "cache_env": m1.os_cache_state(),
        "study": STUDY,
        "quickcheck": quickcheck,
        "quickcheck_note": "β 列 M1 基线 120/120、eps_beta M1 [2.743,3.053]；"
                           "记录非门（criteria 批后快检节）",
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    JUDGMENT_PATH.write_text(
        json.dumps(judgment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[m3] 判读: {judgment['verdict']}  预算: {budget_status}")
    for k, g in judgment["gates"].items():
        print(f"  {k}: pass={g['pass']} {g}")
    print(f"[m3] 快检: {json.dumps(quickcheck, ensure_ascii=False)}")
    return 0 if judgment["pass"] and not partial else 1


def run_materialize() -> int:
    """离线物化+判读（幂等重跑；输入=index + 已落盘产物）。"""
    index = _load_index()
    if not index:
        print("[m3] 无 points_index（先 --collect）")
        return 2
    plan, _errs = _load_or_build_plan()
    walls = [float(r["wall_s"]) for r in index.values()
             if isinstance(r, dict) and r.get("status") == "done"]
    return _finalize(index, plan, walls, False, time.time(), measure_budget=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="M3 谷区定向加密采集（criteria 预声明判据）")
    ap.add_argument("--plan", action="store_true", help="采样计划落盘/打印")
    ap.add_argument("--audit", action="store_true", help="PG1 渲染审计（离线）")
    ap.add_argument("--benchmark", action="store_true", help="PG0 合成非退化门（离线）")
    ap.add_argument("--collect", action="store_true", help="真机批量采集（共享锁内）")
    ap.add_argument("--materialize", action="store_true", help="物化+判读+快检（离线）")
    args = ap.parse_args(argv)
    chosen = sum(1 for f in (args.plan, args.audit, args.benchmark,
                             args.collect, args.materialize) if f)
    if chosen != 1:
        ap.print_help()
        return 2
    if args.plan:
        plan, errs = _load_or_build_plan()
        print(json.dumps(plan["stats"], ensure_ascii=False, indent=1))
        core = [p for p in plan["points"] if p.get("kind") == "core"]
        lhs = [p for p in plan["points"] if p.get("kind") == "lhs"]
        print("谷芯 10 点: " + ", ".join(f"{p['w_mm']:.7f}" for p in core))
        print("LHS 20 点: " + ", ".join(f"{p['w_mm']:.4f}" for p in lhs))
        for e in errs[:3]:
            print(f"  [warn] {e}")
        return 0
    if args.audit:
        return run_audit()
    if args.benchmark:
        return run_benchmark()
    if args.collect:
        return run_collect(REPO)
    return run_materialize()


if __name__ == "__main__":
    sys.exit(main())
