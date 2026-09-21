"""数据工厂二期 A 批·mline 2D 扩展采集驱动（datafactory_phase1_plan §2/§5）。

判据/口径全部预声明 runs/datafactory_m2d_20260921/criteria.md v2（写死再跑，
2026-09-21）。骨架整体搬 factory_m3_valley（锁/互斥/探针/resume，只复制不改
源）：共享锁 runs/.oe_collect.lock + #261 命令行互斥（fail-closed 不代杀）+
QuotaGuard(120 trials, 3.0h) + 首点 ingest 探针（#251④）+ provenance 覆盖 +
port_beta mtime 归属 + points_index.json 崩溃安全 resume。采样与逐点参数换
2D：w_mm∈[0.5,2.0] × line_len_mm∈[20,60]，LHS 111（seed=20260921）+ 锚点 9。

实现契约（criteria §1 末尾，机制核对风险清单）：
- opt_params 显式双键 dict 传 write_run_products（C-05：键不在则第二维静默
  不入数据集行——_single_run_params 按 optimization.params 键集成行）；
- 逐点 line_len 进渲染（set_variables）与 compute_point_metrics（S21 斜率
  口径 eps_eff 依赖它，传常量=40mm 污染）；meta.json/metrics 的 line_len
  写参数值不写常量——m1.write_run_products 的 payload/meta 字段读模块全局
  LINE_LEN_MM，本驱动经 _write_run_products_2d 临时置全局为逐点值（try/
  finally 还原），单测钉死三产物（meta/metrics/recipe）全带逐点值；
- 点 id 含双参数段 a2d_w<µm>_<pm>（m1 式 w-only 会撞名）；
- 批内查重键=(w,line_len) 双键指纹；跨批不剔 M1——(w,40) 重合由引擎缓存
  秒回合法处理（#158），成行标注 cached=true，计入成行、不计入时长统计
  （缓存命中路径 _load_cached 提前返回，eval 目录无 sparams.csv 引擎产物，
  is_cached_run 据此判定，criteria §2 G2）。

用法（cwd=仓库根）：
  python scripts/factory_a2d_collect.py --plan         # 采样计划落盘（不可变）
  python scripts/factory_a2d_collect.py --audit        # 渲染审计 3 点（离线）
  python scripts/factory_a2d_collect.py --collect      # 真机批量（共享锁内；resume）
  python scripts/factory_a2d_collect.py --materialize  # 物化+判读+快检（离线）
  python scripts/factory_a2d_collect.py --judge        # 三门判读（幂等重跑）

退出码：--collect/--audit/--judge/--materialize 0=门过；1=门未达/执行失败；
2=参数错误。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 采集链复用（只 import 不改源，b9aa07a 先例）：m1 模块导入时自注入 src 路径，
# 脚本目录经 python 运行/测试 sys.path 注入解析（本文件 cwd 守卫=仓库根）。
import factory_m1_collect as m1
from factory_m1_collect import (
    compute_point_metrics,
    os_cache_state,
)

# ─── 预声明常量（criteria.md 同源，改门先改 criteria 再改这里） ────────────────
REPO = Path(__file__).resolve().parents[1]
TEMPLATE = "mline"
SUBSTRATE = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # 同 M1 锚口径
FREQ_RANGE_GHZ = (2.0, 3.0)
W_LOW, W_HIGH = 0.5, 2.0
L_LOW, L_HIGH = 20.0, 60.0
N_LHS = 111
LHS_POOL = 130
LHS_MAX_POOLS = 3
LHS_SEED = 20260921
LHS_MIN_DIST = 0.02                    # criteria：归一化空间 0.02
#: 9 锚点（criteria §1：(role, w_mm, line_len_mm)）
ANCHORS: tuple[tuple[str, float, float], ...] = (
    ("corner", 0.5, 20.0),
    ("corner", 0.5, 60.0),
    ("corner", 2.0, 20.0),
    ("corner", 2.0, 60.0),
    ("nominal", 1.113, 40.0),
    ("e11_bound", 0.745, 40.0),
    ("e11_bound", 1.182, 40.0),
    ("len_endpoint", 1.113, 20.0),
    ("len_endpoint", 1.113, 60.0),
)
STUDY = "datafactory_a2d"
SOLVE_TIMEOUT_S = 900.0
QUOTA_TRIALS = 120
QUOTA_WALL_H = 3.0
MEDIAN_WALL_GATE_S = 60.0              # criteria G2：真跑点 wall 中位 ≤60s
MAX_WALL_GATE_S = 120.0                # criteria G2：且单点 ≤120s（cached 排除）
MIN_ROWS_GATE = 100                    # criteria G3：≥100 有效行
DATASET_NAME = "datafactory_a2d_mline_20260921"
PROBE_DATASET = "datafactory_a2d_ingest_probe"
BUDGET_WALL_S = 3.0 * 3600.0           # criteria §3：采集预期 1.2-1.6h，预算 3h
PARTIAL_FACTOR = 1.5                   # 超 1.5×（4.5h）→ PARTIAL(超预算)
ROOT = REPO / "runs" / "datafactory_a2d"
PLAN_PATH = ROOT / "plan.json"
INDEX_PATH = ROOT / "points_index.json"
AUDIT_PATH = ROOT / "render_audit.json"
JUDGMENT_DIR = REPO / "runs" / "datafactory_m2d_20260921"
JUDGMENT_PATH = JUDGMENT_DIR / "judgment.json"
CRITERIA_REL = "runs/datafactory_m2d_20260921/criteria.md"
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
LOCK_POLL_S = 60.0
#: opt_params 双键（C-05 契约面；_single_run_params 按 optimization.params 键集成行）
OPT_PARAMS_2D: dict[str, dict[str, float]] = {
    "w_mm": {"low": W_LOW, "high": W_HIGH},
    "line_len_mm": {"low": L_LOW, "high": L_HIGH},
}
#: PG1 审计三角（criteria §4）：域角 (0.5,20)/(2.0,60) + 名义 (1.113,40)
AUDIT_POINTS: tuple[tuple[float, float], ...] = (
    (0.5, 20.0), (2.0, 60.0), (1.113, 40.0))

__all__ = [
    "a2d_fingerprint",
    "build_a2d_plan",
    "is_cached_run",
    "judge_batch",
    "pending_points",
    "write_run_products_2d",
]


# ─── 纯逻辑（单测钉死面，零引擎零 IO） ────────────────────────────────────────

def a2d_fingerprint(w: float, line_len: float) -> tuple[int, int]:
    """(w,line_len) 双键查重指纹（各 round 1e-6；criteria 存量查重口径的 2D 扩）。"""
    return round(float(w) * 1e6), round(float(line_len) * 1e6)


def _point_id(w: float, line_len: float, used: set[str]) -> str:
    """点 id（a2d_w<µm 四位>_l<pm 五位>）；四舍五入撞名时追加序号守卫（M1 同法）。

    双参数段防撞名（m1 式 w-only 会撞名，criteria 实现契约）；len 段取
    0.001mm 分辨率（LHS len 连续值，2 位整数会高频撞名）。
    """
    base = f"a2d_w{round(float(w) * 1000):04d}_l{round(float(line_len) * 1000):05d}"
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"


def build_a2d_plan() -> dict[str, Any]:
    """采样计划（纯函数，恰 120 点）：锚点 9 + LHS 111（2D 空间填充）。

    批内查重键=(w,line_len) 双键指纹（锚点先占键，LHS 撞键剔除换池续抽，
    至多 LHS_MAX_POOLS 轮）；跨批不剔 M1（criteria：重合由引擎缓存秒回合法
    处理 #158，成行标 cached）。点序：锚点（预声明序）在前、LHS (w,l) 升序
    在后（stable、resume 幂等）。
    """
    from rfauto.optimization.sample_design import lhs_points

    taken: set[tuple[int, int]] = set()
    points: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for role, w, len_mm in ANCHORS:
        taken.add(a2d_fingerprint(w, len_mm))
        pid = _point_id(w, len_mm, used_ids)
        used_ids.add(pid)
        points.append({"point_id": pid, "w_mm": float(w),
                       "line_len_mm": float(len_mm),
                       "kind": "anchor", "anchor_role": str(role)})

    lhs: list[tuple[float, float]] = []
    n_lhs_dropped = 0
    pool_seed = LHS_SEED
    for _pool_i in range(LHS_MAX_POOLS):
        res = lhs_points(
            {"w_mm": (W_LOW, W_HIGH), "line_len_mm": (L_LOW, L_HIGH)},
            LHS_POOL, seed=pool_seed,
            include=[{"w_mm": w, "line_len_mm": len_mm}
                     for _r, w, len_mm in ANCHORS],
            min_dist=LHS_MIN_DIST)
        pool_seed += 1
        for pt in res["points"]:
            w = float(pt["w_mm"])
            len_mm = float(pt["line_len_mm"])
            if a2d_fingerprint(w, len_mm) in taken:
                n_lhs_dropped += 1
                continue
            taken.add(a2d_fingerprint(w, len_mm))
            lhs.append((w, len_mm))
            if len(lhs) >= N_LHS:
                break
        if len(lhs) >= N_LHS:
            break
    lhs = lhs[:N_LHS]

    for w, len_mm in sorted(lhs):
        pid = _point_id(w, len_mm, used_ids)
        used_ids.add(pid)
        points.append({"point_id": pid, "w_mm": float(w),
                       "line_len_mm": float(len_mm),
                       "kind": "lhs", "anchor_role": None})
    return {
        "points": points,
        "stats": {
            "n_anchors": len(ANCHORS),
            "n_lhs_requested": N_LHS,
            "n_lhs_kept": len(lhs),
            "n_lhs_dropped": n_lhs_dropped,
            "n_plan_total": len(points),
            "lhs_seed": LHS_SEED,
            "lhs_pool": LHS_POOL,
            "lhs_min_dist": LHS_MIN_DIST,
            "dedup_mode": "in_batch_only(跨批不剔 M1，(w,40) 重合缓存秒回 #158)",
            "bounds": {"w_mm": [W_LOW, W_HIGH], "line_len_mm": [L_LOW, L_HIGH]},
        },
    }


def judge_batch(
    attempted: int,
    n_rows: int,
    walls_real_s: list[float],
    n_cached: int = 0,
    median_gate_s: float = MEDIAN_WALL_GATE_S,
    max_wall_gate_s: float = MAX_WALL_GATE_S,
    min_rows: int = MIN_ROWS_GATE,
) -> dict[str, Any]:
    """批内三门判定（纯函数；criteria §2 G1/G2/G3，FAIL 如实不凑绿）。

    G2 只统计真跑点墙钟（cached 点排除）；零真跑样本=异常态如实 FAIL
    （fail-closed，不冒充 PASS）。
    """
    row_rate = (float(n_rows) / attempted) if attempted > 0 else 0.0
    med = float(statistics.median(walls_real_s)) if walls_real_s else None
    mx = float(max(walls_real_s)) if walls_real_s else None
    g1 = attempted > 0 and n_rows == attempted
    g2 = med is not None and mx is not None and (
        med <= float(median_gate_s) and mx <= float(max_wall_gate_s))
    g3 = n_rows >= int(min_rows)
    gates = {
        "G1_row_rate_100pct": {
            "pass": bool(g1), "n_attempted": attempted, "n_rows": n_rows,
            "row_rate": round(row_rate, 6), "n_cached_rows": int(n_cached)},
        "G2_real_wall_median_le_60s_and_max_le_120s": {
            "pass": bool(g2),
            "median_wall_s": None if med is None else round(med, 2),
            "max_wall_s": None if mx is None else round(mx, 2),
            "n_real_points": len(walls_real_s),
            "n_cached_excluded": int(n_cached),
            "gate_median_s": float(median_gate_s),
            "gate_max_s": float(max_wall_gate_s),
            "note": "cached 点不入时长统计（criteria G2）；零真跑样本如实 FAIL"},
        "G3_rows_ge_100": {
            "pass": bool(g3), "n_rows": n_rows, "gate": int(min_rows)},
    }
    passed = bool(g1 and g2 and g3)
    fails = [k for k, g in gates.items() if not g["pass"]]
    verdict = "PASS" if passed else f"FAIL: {'; '.join(fails)}"
    return {"pass": passed, "verdict": verdict, "gates": gates}


def pending_points(plan: dict[str, Any], index: dict[str, Any]) -> list[dict[str, Any]]:
    """resume 待跑点（points_index 里 status=done 的点跳过；纯函数）。"""
    out: list[dict[str, Any]] = []
    for pt in plan["points"]:
        row = index.get(str(pt["point_id"]))
        if isinstance(row, dict) and row.get("status") == "done":
            continue
        out.append(pt)
    return out


def latest_eval_dir(evals_root: Path, t_start: float) -> Path | None:
    """solve 起点后 mtime 最新的 eval_* 目录（M3 mtime 归属同法，防串味）。"""
    cands = []
    for d in evals_root.glob("eval_*"):
        mt = d.stat().st_mtime
        if mt >= t_start - 2.0:
            cands.append((mt, d))
    if not cands:
        return None
    return max(cands, key=lambda t: t[0])[1]


def is_cached_run(eval_dir: Path | None) -> bool:
    """缓存命中判定（criteria G2 cached 语义的可观测信号）。

    缓存路径 OpenEMSSolver._load_cached 在子进程求解前提前返回——本点
    eval 目录只有渲染出的 simulation.py，无引擎产物 sparams.csv；真跑
    （成功态）必落 sparams.csv（模板脚本写脚本自身目录）。None=目录缺失
    （纯缓存直返）按命中处理。
    """
    if eval_dir is None:
        return True
    return not (eval_dir / "sparams.csv").exists()


def write_run_products_2d(
    run_dir: Path,
    w_mm: float,
    line_len_mm: float,
    network: Any,
    wall_s: float,
    eval_dir: str,
    metrics: dict[str, float],
    notes: list[str],
) -> None:
    """2D 标准 run 产物落盘（m1.write_run_products 复用 + 常量钉住修正）。

    criteria 实现契约：meta.json/metrics 的 line_len 写参数值不写常量——
    m1.write_run_products 的 metrics payload 与 write_meta 两处读模块全局
    LINE_LEN_MM（recipe.params 用函数参 line_len_mm），故调用期间临时置
    全局为逐点值、try/finally 还原；opt_params 显式双键（C-05：缺键则
    第二维静默不入数据集行）。单测钉死三产物全带逐点值。
    """
    original = m1.LINE_LEN_MM
    m1.LINE_LEN_MM = float(line_len_mm)
    try:
        m1.write_run_products(
            run_dir, float(w_mm), network, wall_s, eval_dir, metrics, notes,
            line_len_mm=float(line_len_mm), opt_params=json.loads(json.dumps(OPT_PARAMS_2D)))
    finally:
        m1.LINE_LEN_MM = original


# ─── 共享锁（与 M1/M3/M4 采集任务互斥；criteria §3） ─────────────────────────

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
    """O_CREAT|O_EXCL 原子建锁；占用则 60s 轮询并打印等待日志（M3 同法）。"""
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
                print(f"[a2d] 陈锁接管（持有者 pid={pid} 已死）：{holder}")
                with contextlib.suppress(OSError):
                    LOCK_PATH.unlink()
                continue
            print(f"[a2d] 锁被占（{holder or '未知持有者'}），{poll_s:.0f}s 后重试…",
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


# ─── 离线面（锁外）：渲染审计 ─────────────────────────────────────────────────

def render_audit_point(w_mm: float, line_len_mm: float) -> dict[str, Any]:
    """PG1 单点审计：render_script（mesh 0=与求解同参 #368）→ exec 网格段。

    判据（criteria §4，#212 制度化）：渲染+exec 无守卫抛错；uniform 线
    原语迹线 x 向宽=设计 w（±1e-6 mm）且 y 向长=设计 line_len（±1e-6 mm）
    ——双参数都须驱动几何；全轴网格最小线距如实记录（信息项非门）。
    """
    from rfauto.adapters.openems_templates import render_script

    text = render_script(
        TEMPLATE, {"w_mm": float(w_mm), "line_len_mm": float(line_len_mm)},
        FREQ_RANGE_GHZ, mesh_resolution_mm=0.0, substrate=dict(SUBSTRATE))
    cut = text.index("FDTD.Run(")
    scope: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(REPO / "_factory_a2d_render_audit.py"),
    }
    exec(compile(text[:cut], "factory_a2d_render_audit", "exec"), scope)
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
    # uniform 线原语：金属中 y 向长度最接近设计 line_len 者（馈线段长度
    # =60−len/2 与 len 区分；名义点 (1.113,40) 两者同为 40mm，量测值相同
    # 不影响判定）
    trace = min(metal_boxes,
                key=lambda p: abs(float(p[1][1] - p[0][1]) - line_len_mm * 1e-3))
    w_meas_mm = float(trace[1][0] - trace[0][0]) * 1e3
    l_meas_mm = float(trace[1][1] - trace[0][1]) * 1e3
    if abs(w_meas_mm - float(w_mm)) > 1e-6:
        raise RuntimeError(
            f"迹线 x 宽 {w_meas_mm:.9f}mm ≠ 设计 {w_mm:.6f}mm（w 未驱动几何？）")
    if abs(l_meas_mm - float(line_len_mm)) > 1e-6:
        raise RuntimeError(
            f"迹线 y 长 {l_meas_mm:.9f}mm ≠ 设计 {line_len_mm:.6f}mm"
            "（line_len 未驱动几何？）")
    mesh_lines: dict[str, int] = {}
    mesh_min: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        try:
            lines = np.asarray(scope["mesh"].GetLines(axis), dtype=float)
        except Exception as exc:  # 网格对象缺失=审计失败面
            raise RuntimeError(f"mesh.GetLines({axis}) 失败: {exc!r}") from exc
        if lines.size < 2:
            raise RuntimeError(f"{axis} 向网格线不足")
        d = np.diff(np.sort(lines))
        mesh_lines[axis] = int(lines.size)
        mesh_min[axis] = float(d.min())
    return {
        "w_mm": float(w_mm), "line_len_mm": float(line_len_mm), "ok": True,
        "n_metal_prims": len(metal_boxes),
        "trace_w_meas_mm": round(w_meas_mm, 9),
        "trace_len_meas_mm": round(l_meas_mm, 9),
        "mesh_n_lines": mesh_lines,
        "mesh_min_spacing_m": {k: float(f"{v:.6g}") for k, v in mesh_min.items()},
        "note": "渲染成功+无守卫抛错+双参数驱动几何（#212/#368 同参 mesh 0 档）",
    }


def run_audit() -> int:
    """PG1 渲染审计（离线，锁外；写 render_audit.json；不过不开跑）。"""
    recs = []
    ok = True
    for w, len_mm in AUDIT_POINTS:
        try:
            rec = render_audit_point(w, len_mm)
        except Exception as exc:
            rec = {"w_mm": float(w), "line_len_mm": float(len_mm), "ok": False,
                   "error": repr(exc)}
            ok = False
        recs.append(rec)
        print(f"[a2d] PG1 (w={w:.4f}, len={len_mm:.2f}): ok={rec['ok']}"
              + ("" if rec["ok"] else f" error={rec.get('error')}"))
    payload = {"gate": "PG1_render_audit_2d", "pass": ok, "points": recs,
               "criteria": CRITERIA_REL,
               "ts": datetime.now(timezone.utc).isoformat()}
    ROOT.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[a2d] PG1 判定: {'PASS' if ok else 'FAIL'} → {AUDIT_PATH}")
    return 0 if ok else 1


# ─── 真机采集（锁内）与物化判读（锁外） ───────────────────────────────────────

def _load_or_build_plan() -> dict[str, Any]:
    """计划不可变（首次生成后 resume 同计划）。"""
    if PLAN_PATH.exists():
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan = build_a2d_plan()
    ROOT.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan


def _load_index() -> dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def _save_index(index: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def done_run_ids(index: dict[str, Any]) -> list[str]:
    """index 里 status=done 的 rid（物化输入；落盘序稳定）。"""
    return [row["rid"] for _pid, row in sorted(index.items())
            if isinstance(row, dict) and row.get("status") == "done"]


def _patch_provenance(run_dir: Path) -> None:
    """写后 provenance 修正（criteria 落盘节）：meta.source/criteria + notes。

    study 字段已在 write_run_products 内经 m1.STUDY 覆盖为 datafactory_a2d；
    此处只修写死的 M1 字面残留（meta.source、criteria 引用、notes 文本）。
    """
    meta_p = run_dir / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["source"] = "factory_a2d_collect"
    meta["criteria"] = CRITERIA_REL
    meta_p.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    rec_p = run_dir / "recipe.snapshot.yaml"
    text = rec_p.read_text(encoding="utf-8")
    text = (text
            .replace("datafactory_m1 采集点", "datafactory_a2d 2D 采集点")
            .replace("runs/data_factory_m1/criteria.md", CRITERIA_REL))
    rec_p.write_text(text, encoding="utf-8")


def run_collect(repo_root: Path) -> int:
    """真机批量采集（共享锁内整段；断点 resume 幂等；缓存命中合法）。"""
    if str(Path.cwd().resolve()) != str(repo_root.resolve()):
        print(f"[a2d] 拒跑：cwd 必须是仓库根 {repo_root}（当前 {Path.cwd()}）")
        return 2
    from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir
    from rfauto.pipeline.quota_guard import QuotaExceededError, QuotaGuard, QuotaLimits
    from rfauto.service.dataset_service import materialize_dataset

    plan = _load_or_build_plan()
    index = _load_index()
    print(f"[a2d] plan={plan['stats']['n_plan_total']} 点 "
          f"(锚 {plan['stats']['n_anchors']} + LHS {plan['stats']['n_lhs_kept']}，"
          f"批内撞键剔除 {plan['stats']['n_lhs_dropped']}；跨批不剔 M1"
          f"（缓存秒回 #158）；缓存态 {os_cache_state()})")

    # provenance：STUDY 覆盖（recipe.study / meta.study_name 随 write 生效）
    m1.STUDY = STUDY

    evals_root = ROOT / "evals"
    adapter = OpenEMSOptAdapter(
        FREQ_RANGE_GHZ, template=TEMPLATE, substrate=SUBSTRATE,
        solve_timeout_s=SOLVE_TIMEOUT_S, work_root=evals_root)
    guard = QuotaGuard(QuotaLimits(max_trials=QUOTA_TRIALS, max_wall_hours=QUOTA_WALL_H))
    import os as _os

    owner_pid = _os.getpid()
    acquire_lock("factory_a2d_collect")
    t0 = time.time()
    walls_real: list[float] = []
    n_cached = 0
    n_attempted = 0
    ingest_checked = False
    partial = False
    try:
        foreign = oe_foreign_running()
        if foreign:
            print("[a2d] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：\n"
                  + "\n".join(f"  {ln}" for ln in foreign[:10]))
            return 1
        print("[a2d] #261 命令行查：无他轨 OE 进程，锁内起跑")
        for pt in plan["points"]:
            pid = str(pt["point_id"])
            row = index.get(pid)
            if isinstance(row, dict) and row.get("status") == "done":
                n_attempted += 1
                if row.get("cached"):
                    n_cached += 1
                else:
                    walls_real.append(float(row["wall_s"]))
                continue
            guard.check_trial(n_attempted)
            guard.check_wall_time(t0)
            n_attempted += 1
            w = float(pt["w_mm"])
            len_mm = float(pt["line_len_mm"])
            rid = generate_run_id()
            run_dir = create_run_dir(repo_root, rid)
            adapter.set_variables({"w_mm": w, "line_len_mm": len_mm})
            t_solve_wall = time.time()       # 墙钟（对 eval 目录 mtime 归属）
            t_solve_mono = time.monotonic()  # 单调钟（墙钟时长）
            rep = adapter.solve(timeout_s=SOLVE_TIMEOUT_S)
            solve_wall = time.monotonic() - t_solve_mono
            if not rep.success:
                index[pid] = {"status": "failed", "rid": rid,
                              "msg": str(rep.message)[:300]}
                _save_index(index)
                print(f"[a2d] {pid} FAIL solve: {rep.message}")
                continue
            eval_dir = latest_eval_dir(evals_root, t_solve_wall)
            cached = is_cached_run(eval_dir)
            net = adapter.get_sparams()
            beta_csv = (eval_dir / "port_beta.csv") if (
                eval_dir is not None and (eval_dir / "port_beta.csv").exists()) else None
            metrics, notes = compute_point_metrics(net, port_beta_csv=beta_csv,
                                                   line_len_mm=len_mm)
            write_run_products_2d(run_dir, w, len_mm, net, solve_wall,
                                  str(adapter.eval_root), metrics, notes)
            _patch_provenance(run_dir)
            index[pid] = {"status": "done", "rid": rid, "w_mm": w,
                          "line_len_mm": len_mm,
                          "kind": str(pt.get("kind", "")),
                          "cached": bool(cached), "wall_s": round(solve_wall, 2)}
            _save_index(index)
            if cached:
                n_cached += 1
            else:
                walls_real.append(solve_wall)
            eps = metrics.get("eps_eff_beta_mean_in_band")
            print(f"[a2d] {pid} rid={rid} wall={solve_wall:.1f}s "
                  f"cached={cached} "
                  f"s11_min={metrics.get('s11_db_min_in_band')}dB "
                  f"eps_beta={eps if eps is not None else 'skipped'}", flush=True)
            # 放量纪律（#251④）：首点 ingest 核对成行才继续批量（独立探针数据集）
            if not ingest_checked:
                probe = materialize_dataset(
                    run_ids=[rid], name=PROBE_DATASET, health_gate=True)
                n_probe = int(probe.get("n_rows") or 0)
                if not probe.get("ok") or n_probe != 1:
                    print(f"[a2d] 首点 ingest 核对失败（ok={probe.get('ok')} "
                          f"n_rows={n_probe} errors={probe.get('errors')} "
                          f"unhealthy={probe.get('unhealthy_runs')}）——停批排查")
                    return 1
                print("[a2d] 首点 ingest 核对 OK（1 行成行，health gate 不拦）")
                ingest_checked = True
    except QuotaExceededError as exc:
        partial = True
        print(f"[a2d] quota 停批（PARTIAL 判定，已完成点照常入库）: {exc}")
    finally:
        release_lock(owner_pid)

    return _finalize(index, plan, walls_real, n_cached, n_attempted, partial, t0)


def _finalize(index: dict[str, Any], plan: dict[str, Any], walls_real: list[float],
              n_cached: int, n_attempted: int, partial: bool, t0: float,
              measure_budget: bool = True) -> int:
    """物化+三门判读+快检（锁外离线面；幂等）。

    measure_budget=False（--materialize/--judge 幂等重跑入口）时预算态按
    "recomputed(见 collect 批次 judgment)" 记，不用本次 0 墙钟误标。
    """
    from rfauto.service.dataset_service import materialize_dataset, query_dataset

    rids = done_run_ids(index)
    n_done = len(rids)
    n_failed = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "failed")
    attempted = n_attempted if n_attempted > 0 else n_done + n_failed
    batch_wall = time.time() - t0
    print(f"[a2d] 批量墙钟 {batch_wall:.0f}s；done={n_done} failed={n_failed} "
          f"cached={n_cached}")

    n_rows = -1
    n_unhealthy = n_skipped = 0
    if rids:
        mat = materialize_dataset(run_ids=rids, name=DATASET_NAME, health_gate=True)
        if mat.get("ok"):
            n_rows = int(mat.get("n_rows") or 0)
            n_unhealthy = len(mat.get("unhealthy_runs") or [])
            n_skipped = len(mat.get("skipped_runs") or [])
            print(f"[a2d] 物化 ok rows={n_rows} unhealthy={n_unhealthy} "
                  f"skipped={n_skipped} dup={mat.get('n_dup')}")
        else:
            print(f"[a2d] 物化失败: {mat.get('errors')}")
    else:
        print("[a2d] 无 done 点可物化")

    judgment = judge_batch(attempted, max(n_rows, 0), walls_real, n_cached)
    # 预算态（criteria §3：≤3h 目标 / >1.5× PARTIAL / 中间=超目标注记）
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

    # 批后快检（记录非门）：β 列覆盖 / eps_beta 范围 / 锚点与 cached 计数
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
    done_rows = [r for r in index.values()
                 if isinstance(r, dict) and r.get("status") == "done"]
    n_anchor_done = sum(1 for r in done_rows if r.get("kind") == "anchor")
    quickcheck = {
        "beta_col_ratio": beta_ratio,
        "eps_eff_beta_min": min(eps_beta) if eps_beta else None,
        "eps_eff_beta_max": max(eps_beta) if eps_beta else None,
        "n_anchor_collected": n_anchor_done,
        "n_cached_collected": n_cached,
        "note": "β 列 M1 基线 120/120、eps_beta M1 [2.743,3.053]；记录非门",
    }

    judgment["partial_budget"] = partial
    judgment["meta"] = {
        "plan": plan["stats"], "n_failed": n_failed,
        "dataset": DATASET_NAME, "n_rows": max(n_rows, 0),
        "quota": {"trials": QUOTA_TRIALS, "wall_hours": QUOTA_WALL_H},
        "batch_wall_s": round(batch_wall, 1),
        "budget_status": budget_status,
        "cache_env": os_cache_state(),
        "study": STUDY,
        "criteria": CRITERIA_REL,
        "quickcheck": quickcheck,
    }
    JUDGMENT_DIR.mkdir(parents=True, exist_ok=True)
    JUDGMENT_PATH.write_text(
        json.dumps(judgment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[a2d] 判读: {judgment['verdict']}  预算: {budget_status}")
    for k, g in judgment["gates"].items():
        print(f"  {k}: pass={g['pass']} {g}")
    print(f"[a2d] 快检: {json.dumps(quickcheck, ensure_ascii=False)}")
    return 0 if judgment["pass"] and not partial else 1


def run_materialize() -> int:
    """离线物化+判读（幂等重跑；输入=index + 已落盘产物）。"""
    index = _load_index()
    if not index:
        print("[a2d] 无 points_index（先 --collect）")
        return 2
    plan = _load_or_build_plan()
    walls_real = [float(r["wall_s"]) for r in index.values()
                  if isinstance(r, dict) and r.get("status") == "done"
                  and not r.get("cached")]
    n_cached = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "done"
                   and r.get("cached"))
    return _finalize(index, plan, walls_real, n_cached, 0, False, time.time(),
                     measure_budget=False)


def run_judge() -> int:
    """三门判读（幂等离线重跑；输入=index + 已物化数据集，不重物化）。"""
    index = _load_index()
    if not index:
        print("[a2d] 无 points_index（先 --collect）")
        return 2
    from rfauto.service.dataset_service import query_dataset

    plan = _load_or_build_plan()
    q = query_dataset(DATASET_NAME, model="mline", limit=100000)
    n_rows = int(q.get("n_rows") or 0) if q.get("ok") else 0
    walls_real = [float(r["wall_s"]) for r in index.values()
                  if isinstance(r, dict) and r.get("status") == "done"
                  and not r.get("cached")]
    n_cached = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "done"
                   and r.get("cached"))
    n_failed = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "failed")
    n_done = sum(1 for r in index.values()
                 if isinstance(r, dict) and r.get("status") == "done")
    judgment = judge_batch(n_done + n_failed, n_rows, walls_real, n_cached)
    judgment["meta"] = {
        "dataset": DATASET_NAME, "dataset_ok": bool(q.get("ok")),
        "n_failed": n_failed, "study": STUDY, "criteria": CRITERIA_REL,
        "plan": plan["stats"],
    }
    JUDGMENT_DIR.mkdir(parents=True, exist_ok=True)
    JUDGMENT_PATH.write_text(
        json.dumps(judgment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[a2d] 判读: {judgment['verdict']}")
    for k, g in judgment["gates"].items():
        print(f"  {k}: pass={g['pass']} {g}")
    return 0 if judgment["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="数据工厂二期 A 批 mline 2D 采集（criteria 预声明判据）")
    ap.add_argument("--plan", action="store_true", help="采样计划落盘/打印")
    ap.add_argument("--audit", action="store_true", help="PG1 渲染审计 3 点（离线）")
    ap.add_argument("--collect", action="store_true", help="真机批量采集（共享锁内）")
    ap.add_argument("--materialize", action="store_true", help="物化+判读+快检（离线）")
    ap.add_argument("--judge", action="store_true", help="三门判读（幂等重跑）")
    args = ap.parse_args(argv)
    chosen = sum(1 for f in (args.plan, args.audit, args.collect,
                             args.materialize, args.judge) if f)
    if chosen != 1:
        ap.print_help()
        return 2
    if args.plan:
        plan = _load_or_build_plan()
        print(json.dumps(plan["stats"], ensure_ascii=False, indent=1))
        anchors = [p for p in plan["points"] if p.get("kind") == "anchor"]
        lhs = [p for p in plan["points"] if p.get("kind") == "lhs"]
        print("锚点 9: " + ", ".join(
            f"{p['point_id']}({p['anchor_role']})" for p in anchors))
        print("LHS 111 点前 5: "
              + ", ".join(f"({p['w_mm']:.4f},{p['line_len_mm']:.3f})" for p in lhs[:5]))
        print(f"  ...（共 {len(plan['points'])} 点，全量见 {PLAN_PATH}）")
        return 0
    if args.audit:
        return run_audit()
    if args.collect:
        return run_collect(REPO)
    if args.materialize:
        return run_materialize()
    return run_judge()


if __name__ == "__main__":
    sys.exit(main())
