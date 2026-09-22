"""ratrace 时长模型干净补样采样驱动（C14a）。

对 ratrace 模板在指定网格档渲染 + openEMS 真机求解（subprocess 分离、单点硬
超时），按 duration_sample 同构 schema（rfauto.quota_guard.ratrace_duration_samples
.v1）落干净样本行：quality=isolated_single_excitation，wall=子进程总墙钟
（与既有干净集 R2/R3/R10 的 result.json:solve_s 同语义——含网格构建+FDTD+
端口后处理，不含父进程渲染文本生成；渲染在计时窗口之外）。

真机纪律（抄 scripts/factory_m3_valley.py 先例）：
- 共享锁 runs/.oe_collect.lock（O_CREAT|O_EXCL 原子建、60s 轮询、陈锁接管、
  finally 释放、删前校验持有者 pid）；
- #261 互斥：起跑前与每次求解前 oe_foreign_running() 查 python 命令行含
  _rfauto_runner|simulation.py 的他轨进程——命中拒绝起跑，不代杀（fail-closed）；
- 单激励 isolated：excite_port=1 单进程（#208 安全模式），NrTS=100000 无
  EndCriteria（模板官方口径，默认能量判据停机）。

渲染/判读与既有干净样本同源：复用 scripts/ratrace_k_finalize.py 的
_render/_run_openems/_center_from_columns/_gates（R2/R3/R10 同一路径）。
健康门=单激励 4x4 部分矩阵掩码 G11（#314）+ 既有读数门（预声明 criteria.md）。

子命令：
- sample：补样（缺省自动互补选档：既有干净集 {0.2:2, 0.3:1, 0.4:1}，0.2mm
  实测墙钟 7681.6/13936.7s 超单点 3600s 预算被淘汰 → 选 0.4 与 0.3，补齐
  2/2/2 均衡设计）；
- refit：loader 消费新旧档合并（runs/quota_guard 14 样本档按 id 取干净子集
  + R10 档 + 本批新档）→ RobustDurationPredictor 重训 + LOO 如实对比。

用法：
    .venv/Scripts/python.exe scripts/ratrace_duration_sample.py sample
    .venv/Scripts/python.exe scripts/ratrace_duration_sample.py sample --mesh 0.4 --label r12_0p4mm
    .venv/Scripts/python.exe scripts/ratrace_duration_sample.py refit

产物（新档，不碰旧档）：runs/ratrace_clean_sample_<date>/<label>/（simulation.py/
stdout_tail.txt/stderr_tail.txt/sparams.csv/fdtd//result.json/verdict.json）
+ runs/ratrace_clean_sample_<date>/duration_sample.json + criteria.md；
refit 产 runs/ratrace_clean6_retrain/predictor_refit.json。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

#: 共享锁（OE 采集互斥面，与 factory_* 先例同一路径）。
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
LOCK_POLL_S = 60.0

TEMPLATE = "ratrace"
NR_TS_CAP = 100000
N_PORTS = 4
#: 域体积与 R1/R10 同式：(2(BOARD+AIR_SIDE))^2*(H_SUB+AIR_TOP)。
DOMAIN_VOLUME_MM3 = 79315.2
#: duration_sample 同构 schema（0-P2⑱ 归档形态）。
SCHEMA = "rfauto.quota_guard.ratrace_duration_samples.v1"
FIELD_NOTES_REF = "runs/quota_guard/ratrace_duration_samples.json"
DEFAULT_OUT_ROOT = REPO / "runs" / "ratrace_clean_sample_20260921"
RETRAIN_ROOT = REPO / "runs" / "ratrace_clean6_retrain"

#: 既有干净集（登记口径 n=4：R1/R2/R3/R10，runs/quota_guard 14 样本档 +
#: runs/ratrace_03mm_sample R10 档；宽松口径 R4/R5/R6-R9 禁用）。
EXISTING_CLEAN_TIERS: tuple[tuple[str, float], ...] = (
    ("R1", 0.2),
    ("R2", 0.2),
    ("R3", 0.4),
    ("R10", 0.3),
)
#: 档位实测墙钟证据（秒，runs/ 归档 wall_s）——档位预算可行性与互补选择依据。
TIER_WALL_EVIDENCE_S: dict[float, tuple[float, ...]] = {
    0.2: (7681.6, 13936.7),  # R1（仲裁批）/ R2（k 定版 isolated，触 NrTS 顶）
    0.3: (1781.6,),  # R10
    0.4: (756.8,),  # R3
}
#: 候选档全集（本驱动只在这些档上补样）。
CANDIDATE_TIERS: tuple[float, ...] = (0.2, 0.3, 0.4)
#: 预算安全系数：档位实测最大墙钟 <= budget_fraction*单点超时 才可行。
BUDGET_FRACTION = 0.8
#: 新样本 id 分配（既有 id R1..R10 已占用）。
NEW_SAMPLE_IDS: dict[float, str] = {0.3: "R11", 0.4: "R12"}


# ─── 档位选择（确定性、可测） ────────────────────────────────────────────────


def choose_mesh_tiers(
    existing_tiers: list[tuple[str, float]],
    *,
    n_new: int = 2,
    per_point_timeout_s: float = 3600.0,
    candidate_tiers: tuple[float, ...] = CANDIDATE_TIERS,
    tier_wall_evidence_s: dict[float, tuple[float, ...]] | None = None,
    budget_fraction: float = BUDGET_FRACTION,
) -> list[float]:
    """按既有档位分布互补补档；超单点预算的档位淘汰。

    规则（预声明，确定性）：
    1. 预算可行过滤——档位实测最大墙钟（TIER_WALL_EVIDENCE_S）>
       budget_fraction*单点超时 的档位淘汰（0.2mm 实测 7681.6/13936.7s 超
       3600s 预算，淘汰）；
    2. 互补选择——每轮取"既有样本数最少"的可行档（并列取 mesh 更大者，
       精档对时长模型信息量更高），直到补满 n_new 条；
    3. 返回升序。
    """
    evidence = dict(TIER_WALL_EVIDENCE_S)
    if tier_wall_evidence_s:
        evidence.update(tier_wall_evidence_s)
    budget = float(per_point_timeout_s) * float(budget_fraction)
    feasible = [
        t for t in candidate_tiers
        if evidence.get(t) and max(evidence[t]) <= budget
    ]
    counts = {t: sum(1 for _, m in existing_tiers if m == t) for t in feasible}
    picks: list[float] = []
    for _ in range(int(n_new)):
        if not feasible:
            break
        tier = min(feasible, key=lambda x: (counts[x], -x))
        if tier not in picks:
            picks.append(tier)
        counts[tier] += 1
    return sorted(picks)


def label_for(mesh_mm: float) -> str:
    sample_id = NEW_SAMPLE_IDS.get(float(mesh_mm))
    if sample_id is None:
        raise ValueError(f"档位 {mesh_mm} 无 id 分配（NEW_SAMPLE_IDS）")
    return f"{sample_id.lower()}_{format(mesh_mm, 'g').replace('.', 'p')}mm"


# ─── 真机纪律：共享锁 + #261 互斥（factory_m3_valley 先例 + 并发扩展） ───────

#: 他轨 OE 在飞判定（2026-09-22 并发扩展：本仓 openEMS 是 python 进程内
#: FDTD.Run（#261），各轨 OE 宿主进程名不同——_rfauto_runner/simulation.py
#: （本轨与 k_finalize/factory 族）、c3_fullcurve_runner（interdigital stage1/2
#: 编排）、smoke_c3_filter_family（c3 的 OE 宿主进程，引擎进程内跑）、
#: ratrace_duration_sample（本驱动他实例）。命中=忙，等待至空闲才发射。
OE_FOREIGN_PATTERN = re.compile(
    r"_rfauto_runner|simulation\.py|c3_fullcurve|smoke_c3_filter_family"
    r"|ratrace_duration_sample",
    re.IGNORECASE)
#: OE 空闲等待轮询间隔/上限（等待是纪律：忙则轮询，超上限 fail-closed 拒发）。
OE_IDLE_POLL_S = 30.0
OE_IDLE_MAX_WAIT_S = 4 * 3600


def _pid_alive(pid: Any) -> bool | None:
    if not isinstance(pid, int):
        return None
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True, timeout=30)
        return str(pid) in (out.stdout or "")
    except Exception:
        return None


def _ps_lister(work: Path) -> list[tuple[int, int, str]]:
    """真实进程清单（python.exe）：(pid, ppid, cmdline) 三元组列表。

    临时 .ps1 经 powershell -NoProfile -ExecutionPolicy Bypass -File 执行
    （#289：内联 $_ 会被 shell 层展开）。查询失败=如实抛错（fail-closed）。
    """
    work.mkdir(parents=True, exist_ok=True)
    ps1 = work / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "ForEach-Object { '{0}`t{1}`t{2}' -f $_.ProcessId, $_.ParentProcessId, "
        "$_.CommandLine }\n", encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        ps1.unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(f"#261 进程查询失败 rc={out.returncode}: {out.stderr[:300]}")
    rows: list[tuple[int, int, str]] = []
    for ln in (out.stdout or "").splitlines():
        parts = ln.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), parts[2] or ""))
        except ValueError:
            continue
    return rows


def own_ancestry_pids(
    rows: list[tuple[int, int, str]], self_pid: int
) -> set[int]:
    """自身进程树 pid 集（self 沿 ParentProcessId 上溯到根）——互斥判定时
    排除自身链（本驱动 cmdline 含 ratrace_duration_sample，不自匹配死锁）。"""
    parent_of = {pid: ppid for pid, ppid, _ in rows}
    pids: set[int] = set()
    cur: int | None = int(self_pid)
    while cur is not None and cur not in pids:
        pids.add(cur)
        cur = parent_of.get(cur)
    return pids


def foreign_oe_from_lister(
    rows: list[tuple[int, int, str]], own_pids: set[int]
) -> list[str]:
    """模式匹配他轨 OE 在飞行（自身树排除）；命中行原样返回（pid\tcmd）。"""
    foreign = []
    for pid, _ppid, cmd in rows:
        if pid in own_pids:
            continue
        if OE_FOREIGN_PATTERN.search(cmd or ""):
            foreign.append(f"{pid}\t{cmd}")
    return foreign


def oe_foreign_running(
    work: Path,
    *,
    lister: Any = None,
    self_pid: int | None = None,
) -> list[str]:
    """#261 互斥查（并发扩展版）：他轨 OE 在飞清单（自身进程树排除）。"""
    rows = (lister or _ps_lister)(work)
    own = own_ancestry_pids(rows, os.getpid() if self_pid is None else self_pid)
    return foreign_oe_from_lister(rows, own)


def wait_oe_idle(
    work: Path,
    *,
    poll_s: float = OE_IDLE_POLL_S,
    max_wait_s: float = OE_IDLE_MAX_WAIT_S,
    lister: Any = None,
    self_pid: int | None = None,
    log: Any = None,
) -> list[str]:
    """轮询等待 OE 空闲；空闲（空清单）才返回，超上限 fail-closed 抛错。

    返回 [] = 空闲可发射；非空不可能返回（要么继续等，要么抛错）。
    """
    effective_log = log or (lambda msg: print(msg, flush=True))
    started = time.monotonic()
    while True:
        foreign = oe_foreign_running(work, lister=lister, self_pid=self_pid)
        if not foreign:
            return []
        waited = time.monotonic() - started
        if waited > max_wait_s:
            raise RuntimeError(
                f"OE 空闲等待超上限（{max_wait_s:.0f}s），拒绝发射（隔离优先）："
                + "; ".join(f[:160] for f in foreign[:5]))
        effective_log(
            f"[rtdur] OE 在飞（他轨 {len(foreign)} 个），{poll_s:.0f}s 后复查"
            f"（已等 {waited:.0f}s）：{foreign[0][:140]}")
        time.sleep(poll_s)


def acquire_lock(task: str, poll_s: float = LOCK_POLL_S) -> None:
    """O_CREAT|O_EXCL 原子建锁；占用则 60s 轮询、陈锁（持有者已死）接管。"""
    import os

    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
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
                print(f"[rtdur] 陈锁接管（持有者 pid={pid} 已死）：{holder}",
                      flush=True)
                with contextlib.suppress(OSError):
                    LOCK_PATH.unlink()
                continue
            print(f"[rtdur] 锁被占（{holder or '未知持有者'}），{poll_s:.0f}s 后重试…",
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


# ─── 渲染自检（#212 离线审计面，起跑前） ────────────────────────────────────


_EXCITE_LINE_RE = re.compile(r"excite\s*=\s*1 if (\d+) == (\d+) else 0")


def preflight_render_checks(text: str, base_mm: float) -> dict[str, Any]:
    """渲染文本起跑前自检：NrTS 声明/无 EndCriteria/单激励/频点数/Run 调用。"""
    nrts_match = re.search(r"openEMS\(NrTS\s*=\s*(\d+)", text)
    checks: dict[str, Any] = {
        "base_mm": round(float(base_mm), 6),
        "nr_ts_declared": int(nrts_match.group(1)) if nrts_match else None,
        "has_end_criteria_kwarg": bool(
            re.search(r"openEMS\([^)]*EndCriteria\s*=", text)),
        "excite_ports_declared": len(_EXCITE_LINE_RE.findall(text)),
        "excited_ports": [
            int(a) for a, b in _EXCITE_LINE_RE.findall(text) if a == b
        ],
        "freq_points_401": bool(
            re.search(r"linspace\(F0\s*-\s*FC,\s*F0\s*\+\s*FC,\s*401\)", text)),
        "has_fdtd_run": "FDTD.Run(" in text,
    }
    problems = []
    if checks["nr_ts_declared"] != NR_TS_CAP:
        problems.append(f"NrTS={checks['nr_ts_declared']} != {NR_TS_CAP}")
    if checks["has_end_criteria_kwarg"]:
        problems.append("渲染文本含 EndCriteria=（应缺省能量判据停机）")
    if checks["excited_ports"] != [1]:
        problems.append(f"非单激励：excited={checks['excited_ports']}")
    if checks["excite_ports_declared"] != N_PORTS:
        problems.append(f"端口激励声明数 {checks['excite_ports_declared']} != {N_PORTS}")
    if not checks["freq_points_401"]:
        problems.append("频点数非 401")
    if not checks["has_fdtd_run"]:
        problems.append("无 FDTD.Run 调用")
    checks["ok"] = not problems
    checks["problems"] = problems
    return checks


# ─── 判读（G11 部分矩阵掩码 #314 + 既有读数门，与 _judge 同构） ─────────────


_STDOUT_TAIL_RE = re.compile(
    r"Time for ([\d.]+) iterations with ([\d.]+) cells : ([\d.]+) sec")


def judge_run(
    work: Path,
    *,
    mesh_mm: float,
    solve_s: float,
    k_applied: float,
    excite_port: int = 1,
    item: str = "c14a_ratrace_clean_sample",
) -> dict[str, Any]:
    """单 run 判读：sparams/stdout 尾巴/et 时间轴 -> verdict dict（不落盘）。"""
    import numpy as np

    import ratrace_k_finalize as rkf
    from rfauto.core.solve_health import solve_health_check

    tail_path = work / "stdout_tail.txt"
    tail = (
        tail_path.read_text(encoding="utf-8", errors="replace")
        if tail_path.is_file()
        else ""
    )
    csv_path = work / "sparams.csv"
    if not csv_path.is_file():
        raise RuntimeError(f"sparams.csv 缺失（{work}）：{tail[-400:]}")
    data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1)
    if data.ndim != 2 or data.shape[1] != 9:
        raise RuntimeError(f"sparams.csv 形态 {data.shape} 非 (N,9)（9 列契约）")
    f_ghz = data[:, 0] / 1e9
    c = rkf._center_from_columns(
        f_ghz,
        rkf._db(data[:, 1], data[:, 2]),
        rkf._db(data[:, 3], data[:, 4]),
        rkf._db(data[:, 5], data[:, 6]),
        rkf._db(data[:, 7], data[:, 8]),
    )
    gates = rkf._gates(c, excite_port)

    # G11（#314 单激励部分矩阵掩码：仅第 excite_port 行独立已测）
    n_f = data.shape[0]
    s4 = np.zeros((n_f, N_PORTS, N_PORTS), dtype=complex)
    row = excite_port - 1
    for col in range(N_PORTS):
        s4[:, row, col] = data[:, 1 + 2 * col] + 1j * data[:, 2 + 2 * col]
    mask = np.zeros((N_PORTS, N_PORTS), dtype=bool)
    mask[row, :] = True
    et_path = work / "fdtd" / "et"
    if not et_path.is_file():
        raise RuntimeError(f"fdtd/et 缺失（{work}）：无停机时间轴可判读")
    et = np.loadtxt(str(et_path))
    dt_steps = np.diff(et[:, 0])
    health = solve_health_check(
        freq_hz=data[:, 0], s_matrix=s4, s_measured_mask=mask,
        timestep_values=dt_steps)

    m = _STDOUT_TAIL_RE.search(tail)
    nr_ts_measured = int(float(m.group(1))) if m else None
    n_cells = int(float(m.group(2))) if m else None
    fdtd_core_s = float(m.group(3)) if m else None
    hit_cap = (nr_ts_measured == NR_TS_CAP) if nr_ts_measured is not None else None
    stop_reason = ""
    if hit_cap is True:
        stop_reason = "nrts_cap"
    elif hit_cap is False:
        stop_reason = "energy"

    return {
        "item": item,
        "judged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mesh_mm": float(mesh_mm),
        "k_applied": round(float(k_applied), 6),
        "excite_port": excite_port,
        "solve_s": round(float(solve_s), 1),
        "center": c,
        "readout_gates": gates,
        "readout_pass": bool(gates.get("all_pass")),
        "g11": {"ok": health["ok"], "verdict": health["verdict"],
                "factors": health["factors"]},
        "nr_ts_measured": nr_ts_measured,
        "nr_ts_cap_declared": NR_TS_CAP,
        "hit_nr_ts_cap": hit_cap,
        "stop_reason": stop_reason,
        "n_cells": n_cells,
        "fdtd_core_s": fdtd_core_s,
        "dt_s": float(np.median(dt_steps)),
        "t_end_s": float(et[-1, 0]),
        "et_steps": int(et.shape[0] - 1),
        "sparams_rows": int(n_f),
    }


def build_sample_row(
    *,
    sample_id: str,
    mesh_mm: float,
    solve_s: float,
    verdict: dict[str, Any],
    source_rel: str,
    note: str,
) -> dict[str, Any]:
    """duration_sample v1 同构行（字段与 R10 对齐 + 显式 stop_reason）。"""
    tier = f"{format(float(mesh_mm), 'g').replace('.', 'p')}mm"
    return {
        "id": sample_id,
        "template": TEMPLATE,
        "grid_tier": tier,
        "base_mm": float(mesh_mm),
        "n_ports": N_PORTS,
        "n_excitations": 1,
        "wall_s": round(float(solve_s), 1),
        "source": source_rel,
        "date": time.strftime("%Y-%m-%d"),
        "nr_ts_cap_declared": NR_TS_CAP,
        "domain_volume_mm3": DOMAIN_VOLUME_MM3,
        "quality": "isolated_single_excitation",
        "adapter": "openems",
        "nr_ts_measured": verdict["nr_ts_measured"],
        "n_cells": verdict["n_cells"],
        "fdtd_core_s": verdict["fdtd_core_s"],
        "hit_nr_ts_cap": verdict["hit_nr_ts_cap"],
        "stop_reason": verdict["stop_reason"],
        "k_applied": verdict["k_applied"],
        "dt_s": verdict["dt_s"],
        "t_end_s": verdict["t_end_s"],
        "et_steps": verdict["et_steps"],
        "sparams_rows": verdict["sparams_rows"],
        "g11_verdict": verdict["g11"]["verdict"],
        "readout_pass": verdict["readout_pass"],
        "note": note,
    }


def write_duration_sample(out_root: Path, samples: list[dict[str, Any]]) -> Path:
    path = out_root / "duration_sample.json"
    payload = {
        "schema": SCHEMA,
        "field_notes_ref": FIELD_NOTES_REF,
        "samples": samples,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_duration_samples(out_root: Path) -> list[dict[str, Any]]:
    path = out_root / "duration_sample.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("samples", []))


# ─── 单样本执行（调用方先持锁 + #261 互斥通过） ─────────────────────────────


def run_sample(
    mesh_mm: float,
    out_root: Path,
    *,
    timeout_s: int = 3600,
    solve_fn: Any = None,
    foreign_probe: Any = None,
    idle_poll_s: float = OE_IDLE_POLL_S,
    idle_max_wait_s: float = OE_IDLE_MAX_WAIT_S,
    item: str = "c14a_ratrace_clean_sample",
) -> dict[str, Any] | None:
    """渲染 -> 自检 -> 等 OE 空闲 -> 求解（subprocess 分离）-> 判读 -> 落产物。

    隔离纪律（并发扩展）：solve 前 wait-until-idle（忙则轮询等待，隔离优先，
    超上限 fail-closed 抛错）；solve 返回后立即复查一次，发现他轨 OE（存在
    并发可能、无法证清白）如实 isolated=false 降级。solve_fn/foreign_probe
    注入点供测试 mock。返回样本行；求解失败（无 sparams）落 failed result
    并返回 None。
    """
    import ratrace_k_finalize as rkf

    probe = foreign_probe or oe_foreign_running
    mesh_mm = float(mesh_mm)
    sample_id = NEW_SAMPLE_IDS[mesh_mm]
    label = label_for(mesh_mm)
    work = out_root / label
    work.mkdir(parents=True, exist_ok=True)

    text, k_applied, base_mm = rkf._render(mesh_mm, 1, None)
    pre = preflight_render_checks(text, base_mm)
    if not pre["ok"]:
        (work / "preflight.json").write_text(
            json.dumps({"ok": False, "checks": pre}, ensure_ascii=False,
                       indent=2), encoding="utf-8")
        raise RuntimeError(f"[{label}] 渲染自检不过：{pre['problems']}")

    started = time.monotonic()
    wait_rounds = 0
    while True:
        foreign_before = probe(work)
        if not foreign_before:
            break
        wait_rounds += 1
        waited = time.monotonic() - started
        if waited > idle_max_wait_s:
            raise RuntimeError(
                f"[{label}] OE 空闲等待超上限（{idle_max_wait_s:.0f}s），拒绝发射"
                f"（隔离优先）：{foreign_before[:3]}")
        print(f"[rtdur] [{label}] OE 在飞（他轨 {len(foreign_before)} 个），"
              f"{idle_poll_s:.0f}s 后复查（已等 {waited:.0f}s）："
              f"{foreign_before[0][:140]}", flush=True)
        time.sleep(idle_poll_s)

    solve = solve_fn or rkf._run_openems
    print(f"[rtdur] [{label}] mesh={mesh_mm} BASE={base_mm:.4f}mm "
          f"k={k_applied:.6f} timeout={timeout_s}s OE 空闲已确认，求解中…",
          flush=True)
    solve_s, _csv_path, err_tail = solve(work, text, int(timeout_s))
    foreign_after = list(probe(work) or [])
    isolated = not foreign_before and not foreign_after
    if _csv_path is None:
        (work / "result.json").write_text(
            json.dumps({"label": label, "stage": "failed", "mesh_mm": mesh_mm,
                        "solve_s": solve_s, "stderr_tail": err_tail,
                        "isolated": isolated},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[rtdur] [{label}] FAILED solve_s={solve_s}\n{err_tail}",
              flush=True)
        return None

    verdict = judge_run(work, mesh_mm=base_mm, solve_s=solve_s,
                        k_applied=k_applied, item=item)
    verdict["preflight"] = pre
    verdict["isolation"] = {
        "isolated": isolated,
        "wait_rounds": wait_rounds,
        "foreign_before_solve": foreign_before,
        "foreign_after_solve": foreign_after,
        "pattern": OE_FOREIGN_PATTERN.pattern,
    }
    (work / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "result.json").write_text(
        json.dumps({"label": label, "stage": "done", "mesh_mm": mesh_mm,
                    "base_mm": base_mm, "k_applied": k_applied,
                    "solve_s": solve_s, "stop_reason": verdict["stop_reason"],
                    "hit_nr_ts_cap": verdict["hit_nr_ts_cap"],
                    "isolated": isolated,
                    "finished_at": verdict["judged_at"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    source_rel = (
        f"{out_root.name}/{label}/result.json:solve_s (+stdout_tail.txt)")
    row = build_sample_row(
        sample_id=sample_id, mesh_mm=base_mm, solve_s=solve_s,
        verdict=verdict, source_rel=source_rel,
        note=(f"C14a 干净补样（isolated 单激励+总墙钟，n=4 -> n>=6 目标）；"
              f"渲染/停机判据与 R2/R3/R10 同源（k_finalize 路径，"
              f"k={k_applied:.6f}）；G11+读数门判读见 {label}/verdict.json；"
              f"预声明 criteria.md"))
    row["isolated"] = isolated
    if not isolated:
        row["quality"] = "single_excitation_concurrent_risk"
        row["note"] += ("；isolated=false（solve 前后探测到他轨 OE，存在并发"
                        "可能，如实降级不入干净拟合集）")
    samples = [s for s in read_duration_samples(out_root)
               if s.get("id") != sample_id]
    samples.append(row)
    path = write_duration_sample(out_root, samples)
    print(f"[rtdur] [{label}] done wall={solve_s:.1f}s "
          f"nr_ts={verdict['nr_ts_measured']} stop={verdict['stop_reason']} "
          f"readout_pass={verdict['readout_pass']} g11={verdict['g11']['verdict']} "
          f"isolated={isolated} -> {path}", flush=True)
    return row


# ─── criteria.md 预声明（起跑前落盘，跑后不改判据 #122） ────────────────────


def write_criteria_md(out_root: Path, tiers: list[float], timeout_s: int) -> Path:
    path = out_root / "criteria.md"
    if path.exists():
        return path
    tier_lines = "\n".join(
        f"- {m:g}mm -> id={NEW_SAMPLE_IDS[m]} label={label_for(m)}；既有证据墙钟 "
        f"{[w for w in TIER_WALL_EVIDENCE_S.get(m, ())]}s；"
        f"预算 {timeout_s}s（<=0.8 档可行）" for m in tiers)
    text = f"""# criteria.md — c14a ratrace 干净补样（OE 真机 {len(tiers)} 条）

落盘时刻：{time.strftime("%Y-%m-%d %H:%M:%S")}（起跑前预声明，跑后不改判据；#122 如实判读）。

## 1. 样本口径（钉死）

- 干净样本 = isolated 单激励 + 总墙钟：excite_port=1 单进程（#208 安全模式），
  wall = 子进程总墙钟（ratrace_k_finalize._run_openems 计时，含网格构建+FDTD+
  端口后处理，不含父进程渲染文本生成）——与 R2/R3/R10 的 result.json:solve_s
  同语义（同一函数产出）。
- 宽松口径样本禁用：R4/R5（并发污染）、R6-R9（smoke_early_fdtd_core_only，
  FDTD 核心用时非总墙钟）。

## 2. 档位选择（互补，预声明）

既有干净集 {{0.2: R1/R2, 0.3: R10, 0.4: R3}}；0.2mm 实测墙钟 7681.6/13936.7s
超单点 {timeout_s}s 预算（0.8 系数）淘汰 → 补 **0.4 与 0.3**（2/2/2 均衡设计）。

{tier_lines}

## 3. 渲染口径（与 R2/R3/R10 同源）

- ratrace_k_finalize._render(mesh, excite_port=1, k_override=None)：
  render_script("ratrace", {{"w_ring_mm": 0.6035, "w_feed_mm": 1.1134}},
  (2.25, 2.75) GHz, mesh_resolution_mm=<档>, excite_port=1)；
- NrTS=100000 无 EndCriteria（官方默认能量判据停机）；401 频点；k(BASE)=
  ratrace_ring_mesh_k（0.3->1.120439 与 R10 同、0.4->1.1654 锚）；
- 起跑前渲染自检（preflight_render_checks）：NrTS 声明/无 EndCriteria kwarg/
  单激励（excited==[1]）/401 频点/FDTD.Run 存在。

## 4. 停机与健康门（与 R10 criteria.md 同款）

- hit_nr_ts_cap = (nr_ts_measured == 100000)；显式 stop_reason：
  nrts_cap（触顶）/ energy（能量判据提前停机）；
- 读数门（0.4mm b1 参考：center 2.5013GHz / bal 0.001dB / S11@bal −39.32dB /
  S31@bal −35.13dB / S21,S41@bal −3.17dB）：f_center_balance ∈ 2.5GHz±2%；
  bal<=0.5dB；S11@bal<=−20dB；S31@bal<=−20dB；|S21@bal+3.2|<=0.5dB；
  |S41@bal+3.2|<=0.5dB；
- G11 门（core/solve_health.solve_health_check）：单激励 4x4 部分矩阵掩码
  （#314，仅激励行独立已测）+ et 时间轴 diff 单值性（#152 CFL）；
- 判读如实：PASS/FAIL/UNKNOWN 不凑绿；样本质量（记录完整/机制明确）是本批
  目标，时长模型达标与否由 refit 如实落档。

## 5. 真机纪律

- 共享锁 runs/.oe_collect.lock + #261 命令行互斥（起跑前与每次求解前查，
  命中拒绝起跑不代杀）；单点硬超时 {timeout_s}s（subprocess timeout）。
"""
    path.write_text(text, encoding="utf-8")
    return path


# ─── 子命令：sample ─────────────────────────────────────────────────────────


def cmd_sample(args: argparse.Namespace) -> int:
    out_root = Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT
    out_root.mkdir(parents=True, exist_ok=True)
    done_tiers = [(str(s.get("id")), float(s.get("base_mm", 0.0)))
                  for s in read_duration_samples(out_root)]
    if args.mesh is not None:
        tiers = [float(args.mesh)]
    else:
        tiers = choose_mesh_tiers(
            list(EXISTING_CLEAN_TIERS) + done_tiers, n_new=args.n_new,
            per_point_timeout_s=args.timeout)
    tiers = [t for t in tiers
             if float(t) not in [m for _, m in done_tiers]]
    if not tiers:
        print("[rtdur] 无待补档位（新档已含目标样本）", flush=True)
        return 0
    write_criteria_md(out_root, tiers, args.timeout)
    print(f"[rtdur] 补档计划：{tiers} -> out={out_root}", flush=True)

    import os

    owner_pid = os.getpid()
    acquire_lock("ratrace_duration_sample")
    try:
        # 初始等待：忙则轮询至空闲才进入逐样本发射（隔离优先，并发扩展）。
        wait_oe_idle(out_root)
        print("[rtdur] OE 空闲确认，锁内逐样本发射（每条 solve 前后各复查）",
              flush=True)
        rows = []
        for tier in tiers:
            row = run_sample(tier, out_root, timeout_s=args.timeout)
            if row is not None:
                rows.append(row)
        print(json.dumps({"planned_tiers": tiers, "rows": rows},
                         ensure_ascii=False, indent=2), flush=True)
        return 0 if len(rows) == len(tiers) else 1
    finally:
        release_lock(owner_pid)


# ─── 子命令：refit（loader 消费新旧档合并重训） ─────────────────────────────


def _load_duration_samples_with_ids(path: Path) -> dict[str, dict[str, Any]]:
    """loader 装载 + raw id 回贴（loader 逐条顺序消费、跳过条目如实剔除）。

    id 回贴键 = (template, mesh_mm, solve_s)——duration_sample 档内唯一；
    冲突即抛错（不猜）。返回 id -> DurationSample 属性字典。
    """
    from rfauto.pipeline.duration_calibration import load_duration_sample_json

    loaded = load_duration_sample_json(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    by_key: dict[tuple[str, float, float], dict[str, Any]] = {}
    for entry in raw.get("samples", []):
        if not isinstance(entry, dict):
            continue
        template = str(entry.get("template") or "")
        mesh = entry.get("base_mm") or entry.get("mesh_mm")
        wall = entry.get("wall_s")
        if mesh is None or wall is None:
            continue
        key = (template, round(float(mesh), 6), round(float(wall), 4))
        if key in by_key:
            raise ValueError(f"{path}: 样本键冲突 {key}")
        by_key[key] = entry
    out: dict[str, dict[str, Any]] = {}
    for sample in loaded["samples"]:
        key = (sample.template, round(sample.mesh_mm, 6),
               round(sample.solve_s, 4))
        entry = by_key.get(key)
        sample_id = str(entry.get("id")) if entry and entry.get("id") else ""
        if not sample_id:
            raise ValueError(f"{path}: 装载样本 {key} 无 raw id 可回贴")
        out[sample_id] = {
            "mesh_mm": sample.mesh_mm,
            "solve_s": sample.solve_s,
            "domain_volume_mm3": sample.domain_volume_mm3,
            "n_excitations": sample.n_excitations,
            "nrts_limit": sample.nrts_limit,
            "stop_reason": sample.stop_reason,
            "solver": sample.solver,
            "template": sample.template,
            "grid_tier": sample.grid_tier,
            "source": sample.source,
        }
    return out


def cmd_refit(args: argparse.Namespace) -> int:
    import numpy as np

    from rfauto.pipeline.quota_guard import (
        OffsetPowerDurationPredictor,
        RobustDurationPredictor,
    )

    old_path = REPO / "runs" / "quota_guard" / "ratrace_duration_samples.json"
    r10_path = REPO / "runs" / "ratrace_03mm_sample" / "duration_sample.json"
    new_path = (Path(args.out_root) if args.out_root
                else DEFAULT_OUT_ROOT) / "duration_sample.json"
    merged: dict[str, dict[str, Any]] = {}
    provenance: dict[str, list[str]] = {}
    for label, path in (("quota_guard_14", old_path), ("ratrace_03mm", r10_path),
                        ("clean_sample_new", new_path)):
        if not path.is_file():
            provenance[label] = [f"MISSING {path}"]
            continue
        with_ids = _load_duration_samples_with_ids(path)
        merged.update(with_ids)
        provenance[label] = sorted(with_ids)

    clean_ids_all = [sid for sid, _ in EXISTING_CLEAN_TIERS] + [
        NEW_SAMPLE_IDS[0.3], NEW_SAMPLE_IDS[0.4]]
    missing = [sid for sid in clean_ids_all if sid not in merged]
    if missing:
        print(f"[rtdur] refit 缺干净样本：{missing}（先完成 sample）", flush=True)
        return 1

    def _row(sid: str) -> Any:
        d = merged[sid]
        from rfauto.pipeline.quota_guard import DurationSample

        return DurationSample(
            mesh_mm=d["mesh_mm"], solve_s=d["solve_s"],
            domain_volume_mm3=d["domain_volume_mm3"],
            n_excitations=d["n_excitations"], nrts_limit=d["nrts_limit"],
            stop_reason=d["stop_reason"], solver=d["solver"],
            template=d["template"], grid_tier=d["grid_tier"], source=sid)

    sets: dict[str, list[str]] = {
        "baseline_clean4(R1,R2,R3,R10)": ["R1", "R2", "R3", "R10"],
        "isolated_clean5(R2,R3,R10,R11,R12)": ["R2", "R3", "R10", "R11", "R12"],
        "planar_clean6(R1,R2,R3,R10,R11,R12)": clean_ids_all,
    }
    refit: dict[str, Any] = {}
    for name, ids in sets.items():
        rows = [_row(sid) for sid in ids]
        rob = RobustDurationPredictor.fit(rows)
        base = OffsetPowerDurationPredictor.fit(rows)
        loo_max = rob.loo_max
        refit[name] = {
            "n": len(rows),
            "robust_status": rob.status,
            "loo_mean_rel_error": (None if rob.loo_mean is None
                                   else round(rob.loo_mean, 4)),
            "loo_max_rel_error": None if loo_max is None else round(loo_max, 4),
            "loo_rel_errors": {
                rows[i].source: (None if not np.isfinite(e) else round(e, 4))
                for i, e in enumerate(rob.loo_errors)
            },
            "meets_30pct": bool(rob.status == "calibrated" and loo_max is not None
                                and loo_max <= 0.3),
            "offset_s": round(base.offset_s, 2),
            "scale_s": round(base.scale_s, 4),
        }

    RETRAIN_ROOT.mkdir(parents=True, exist_ok=True)
    out = {
        "schema": "rfauto.quota_guard.ratrace_duration_refit.v1",
        "generated_at": time.strftime("%Y-%m-%d"),
        "generated_by": "scripts/ratrace_duration_sample.py refit（既有确定性内核，"
                        "pipeline/duration_calibration.load_duration_sample_json "
                        "消费新旧档合并；零 pipeline 代码改动）",
        "model": "pipeline/quota_guard.OffsetPowerDurationPredictor"
                 "(t=offset+scale*mesh^-3.5*n_exc)+RobustDurationPredictor 三门",
        "nr_ts_feature": "DurationSample 无 NrTS 特征槽（固定形式幂律模型）；"
                         "停机机制以 stop_reason/ nrts_limit 特征随样本装载",
        "provenance": provenance,
        "clean_set": clean_ids_all,
        "refit": refit,
    }
    out_path = RETRAIN_ROOT / "predictor_refit.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="ratrace 时长模型干净补样（C14a）：sample/refit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="补干净样本（缺省自动互补选档）")
    s.add_argument("--mesh", type=float, default=None,
                   help="显式网格档（缺省=互补选档）")
    s.add_argument("--label", default=None, help="仅显式 --mesh 时可用（缺省按 id 命名）")
    s.add_argument("--n-new", type=int, default=2)
    s.add_argument("--timeout", type=int, default=3600)
    s.add_argument("--out-root", default=None)
    s.set_defaults(fn=cmd_sample)
    r = sub.add_parser("refit", help="n=6 干净集重训 + LOO 如实对比")
    r.add_argument("--out-root", default=None)
    r.set_defaults(fn=cmd_refit)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
