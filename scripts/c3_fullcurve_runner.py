"""c3 全收敛档（路线 a）两阶段 runner（budget_replan §二，判据预声明
runs/smoke_c3_redesign/criteria_a.md，写死再跑；铁律 7 数值只出内核/判读器）。

两阶段（每模板 interdigital/combline/sir_bpf，各自分离进程、可独立重跑）：
  stage1 前哨：既有 scripts/smoke_c3_filter_family.py --q-extrap 路径、1.4h 帽
    （--timeout 5040，subprocess 防挂死**非预算门**）→ 解析 ringdown 实测衰减率
    （内核 scripts/c3_resonance_q_extract.py 多模 α + 引擎能量尾段斜率交叉，
    取慢者=保守）→ 前哨门（q_extrap 置信三面 dev/holdout/span + S21∞@f0 ≥−3dB，
    S11∞ 语义切换后降级为记录量）→ PASS 才放行 stage2。
  帽停容忍（2026-09-22 增补）：smoke 内部 --timeout 杀引擎后 TimeoutExpired
    未捕获即崩溃退出（rc=1，smoke 源禁改）——runner 按 elapsed ≥ 4000s 判
    **帽停非 crash**，走部分产物判读（kernel ringdown + 置信三门 + S21∞@f0，
    门数值不动；refix extract_partial 先例：fdtd 剔 kill 残行 → fdtd_partial/
    → 离线判读）产 stage1/stage1_verdict.json；秒退（<4000s）仍 crash 如实
    FAIL。帽窗 < s21_f0 min_duration 属预期，判读主路径=置信门内 ringdown 外推。
  stage2 全收敛档：NrTS = 预测全程×1.5（下限=帽停点步数/激励步数）**先写进
    plan.json 预声明再执行**；EndCriteria 不传 = 引擎缺省 −60dB 不动；
    预算硬帽 = 1.5×wall_pred（超判 PARTIAL(超预算) 不删数据）；combline
    blocked 规则保留（4h 能量 >−10dB 杀树上报）。判读 G0-G4 =
    runs/smoke_c3_refix/judge_refix.py 口径（band_center_3db 脚本内逐位拷贝，
    runs/ 证据树零 import 依赖）+ G1 当轮 PRED_SHIFT
    （当轮频轴 c3_circuit_sparams 重算；cpass_verdict.json 存档值交叉记录）。

**关键物理预声明**：旧衰减率 0.28dB/ns 在旧（失配）设计上测得，重设计失配
消除后衰减动力学不同——stage1 前哨实测衰减率是 NrTS 的唯一合法输入，禁沿用
旧值外推新设计（criteria_a.md §〇）。

用法（cwd=仓库根）：
  python scripts/c3_fullcurve_runner.py --plan                 # 离线：渲染+exec 几何段落 plan 基座
  python scripts/c3_fullcurve_runner.py --template interdigital --stage stage1
  python scripts/c3_fullcurve_runner.py --template interdigital --stage stage2
  python scripts/c3_fullcurve_runner.py --template interdigital --judge
退出码：0=完成/门过；1=门未达/判 FAIL/执行失败；2=参数错误。

产物根 runs/smoke_c3_fullcurve/<template>/{stage1,stage2}/（#279 分档，不混
runs/smoke_c3_refix 归档）。互斥 = runs/.oe_c3_fullcurve.lock（O_CREAT|O_EXCL +
pid 陈锁核验，factory_m3_valley 先例）+ #261 命令行查（fail-closed）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (REPO / "src", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

from c3_resonance_q_extract import load_msl_probes  # noqa: E402  内核探针读入（剔残行守卫预检）

# 伪模分类+物理模基重外推；无伪模返回 None=缺省路径零改动
from c3_spurious_modes import split_physical_refit  # noqa: E402
from rfauto.adapters.openems_templates import (  # noqa: E402
    C3_TEMPLATES,
    TEMPLATE_NOMINAL,
    c3_circuit_sparams,
    c3_mesh_max_mm,
    render_script,
)
from rfauto.core.synthesis import Stackup  # noqa: E402
from smoke_c3_filter_family import (  # noqa: E402  只读 import 不改源
    Q_EXTRAP_DEV_DB_MAX,
    Q_EXTRAP_HOLDOUT_REL_MAX,
    Q_EXTRAP_SPAN_DB_MIN,
    _probe_dir,
    auto_mesh_mm,
    nrts_convergence,
    parse_engine_log,
    q_extrap_report_from_probes,
    q_extrapolation_gate,
)

# ─── 预声明常量（criteria_a.md 同源，改门先改 criteria 再改这里） ────────────────
CRITERIA_A = "runs/smoke_c3_redesign/criteria_a.md"
CPASS_PATH = REPO / "runs" / "smoke_c3_redesign" / "cpass_verdict.json"
NOMINALS_PATH = REPO / "runs" / "smoke_c3_redesign" / "redesign_nominals.json"
ROOT = REPO / "runs" / "smoke_c3_fullcurve"
PLAN_NAME = "plan.json"
LOCK_NAME = ".oe_c3_fullcurve.lock"
SMOKE_SCRIPT = HERE / "smoke_c3_filter_family.py"
SUBSTRATE = "rogers4350b_h0.508"
FREQ_RANGE_GHZ = (2.25, 2.75)            # smoke 缺省扫频带（stage1/stage2 同带）
N_FREQ = 401
F0_GHZ = 2.5
FBW = 0.05
END_CRITERIA_DB = -60.0                  # 引擎缺省（EndCriteria 旋钮不动）
STAGE1_TIMEOUT_S = 5040.0                # 1.4h 帽：防挂死，非预算门
STAGE1_RUNNER_MARGIN_S = 900.0           # runner 侧等待余量（帽由 smoke --timeout 保证）
STAGE1_CAPSTOP_MIN_S = 4000.0            # 帽停 vs 秒退分界：已运行 ≥此值判帽停非 crash
STAGE1_VERDICT_NAME = "stage1_verdict.json"   # 帽停部分产物判读 verdict（不离档）
STAGE2_SMOKE_MARGIN_S = 600.0            # smoke --timeout = 预算硬帽 +600（杀树余量）
STAGE2_RUNNER_MARGIN_S = 900.0           # runner 侧终极挂死守卫余量
SAFETY_NRTS = 1.5                        # NrTS = 预测全程 ×1.5
SAFETY_BUDGET = 1.5                      # 预算硬帽 = wall_pred ×1.5（超判 PARTIAL 不删数据）
ENERGY_RATE_PER_ALPHA_NS = 17.3718       # 能量域 dB/ns per α[1/ns]：2×8.6859（能量∝幅²）
SENTINEL_S21_INF_F0_MIN_DB = -3.0        # 前哨 PASS 第二面：S21∞@f0 带内量级（S11∞ 已降级记录量）
TAIL_RATE_MIN_POINTS = 5                 # 引擎能量尾段斜率可辨识条件
TAIL_RATE_MIN_SPAN_DB = 3.0              # 1.4h 帽窗实测跨度 3-5dB 量级（0.28-0.5dB/ns×10ns）
BLOCKED_TEMPLATE = "combline"
BLOCKED_AFTER_S = 4.0 * 3600.0
BLOCKED_ENERGY_MAX_DB = -10.0
LOCK_POLL_S = 60.0
WATCH_POLL_S = 60.0
# 激励时长（秒）：三模板 refix 引擎实测同值（时长网格无关：interdigital/combline/
# sir_bpf engine.log 均 "Excitation signal length is: N timesteps (1.14592e-08s)"）
T_EXCITE_REF_S = 1.14592e-08
# 旧（失配）设计实测对照列——**禁作新设计 NrTS/预算输入**（criteria_a.md §〇）
OLD_DESIGN_REFERENCE: dict[str, dict[str, Any]] = {
    "interdigital": {"cap_steps": 163654, "cap_energy_db": -13.0,
                     "tail_rate_db_per_ns": 0.28, "full_est_steps": 1.35e6,
                     "wall_est_h": 11.6},
    "sir_bpf": {"cap_steps": 191738, "cap_energy_db": -15.4, "full_est_wall_h": 10.5},
    "combline": {"cap_energy_db": 0.0,
                 "risk": "UNDECIDABLE 风险最高（4h 能量>−10dB 判 blocked）"},
}
G1_PASS_PT = 1.5
G1_PARTIAL_PT = 3.0
G2_PEAK_MIN_DB = -3.0
G2_RL_MAX_DB = -10.0
G3_BAND_REL = 0.02
POWER_SUM_MAX = 1.02
PRED_DRIFT_RECORD_PT = 0.5

_RE_PROG = re.compile(
    r"Timestep:\s+(\d+) \|\|.*?Energy: ~([0-9.eE+-]+) \(\s*(-?[0-9.]+)dB\)")
_C0 = 299792458.0


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stage_dir(template: str, stage: str, root: Path | None = None) -> Path:
    return (root or ROOT) / template / stage


def _lock_path(root: Path | None = None) -> Path:
    if root is None:
        return ROOT.parent / LOCK_NAME
    return Path(root) / LOCK_NAME


# ─── 衰减率解析（criteria_a.md §二，纯函数离线可测）────────────────────────────

def energy_rate_from_alpha(alpha_per_ns: float) -> float:
    """环振慢模 α → 能量域衰减速率 dB/ns（2×8.6859·α）。"""
    a = float(alpha_per_ns)
    if not (a > 0.0 and math.isfinite(a)):
        raise ValueError(f"α 须为正有限数：{alpha_per_ns!r}")
    return ENERGY_RATE_PER_ALPHA_NS * a


def engine_energy_tail_rate(log_text: str, dt_s: float, t_excite_s: float,
                            min_points: int = TAIL_RATE_MIN_POINTS,
                            min_span_db: float = TAIL_RATE_MIN_SPAN_DB,
                            ) -> float | None:
    """引擎日志能量尾段线性斜率 |dB/ns|（激励结束后的 (t, E_dB) 点列拟合）。

    点数 <min_points 或衰减跨度 <min_span_db → None（不可辨识如实返回，#122
    不凑数；此时速率只用 kernel 单边）。
    """
    dt = float(dt_s)
    t_exc = float(t_excite_s)
    if not (dt > 0.0) or not (t_exc >= 0.0):
        return None
    pts = [(int(step) * dt, float(e_db))
           for step, _amp, e_db in _RE_PROG.findall(log_text)
           if int(step) * dt >= t_exc]
    if len(pts) < min_points:
        return None
    t = np.array([p[0] for p in pts])
    e = np.array([p[1] for p in pts])
    if float(e.max() - e.min()) < min_span_db:
        return None
    slope_per_s = float(np.polyfit(t, e, 1)[0])      # dB/s（负=衰减）
    return abs(slope_per_s) * 1e-9


def compute_stage2_plan(dt_s: float, iterations_done: int, excitation_steps: int,
                        e_cap_db: float, alpha_min_per_ns: float,
                        rate_engine_db_per_ns: float | None,
                        stage1_wall_s: float | None,
                        end_criteria_db: float = END_CRITERIA_DB,
                        safety_nrts: float = SAFETY_NRTS,
                        safety_budget: float = SAFETY_BUDGET) -> dict[str, Any]:
    """stage2 NrTS/预算计算（criteria_a.md §二公式，纯函数；合成回收测试钉）。

    t_full = t_cap_end + ΔE / rate_used（帽停锚定，budget_replan
    §二算例同式；ΔE = E_cap − EndCriteria（能量余量 dB，如 −13→−60 差 47）；
    rate_used = min(kernel, engine) 慢者=保守长预测）；
    NrTS_stage2 = max(ceil(safety×NrTS_pred), 帽停步数, 激励步数)；
    stage1 帽内已自然收敛（E_cap ≤ 判据）→ converged_in_stage1。
    """
    dt = float(dt_s)
    if not (dt > 0.0 and math.isfinite(dt)):
        raise ValueError(f"dt_s 须为正有限数：{dt_s!r}")
    done = int(iterations_done)
    n_exc = int(excitation_steps)
    if done <= 0 or n_exc <= 0:
        raise ValueError(f"步数须为正：iterations_done={done} excitation_steps={n_exc}")
    rate_kernel = energy_rate_from_alpha(alpha_min_per_ns)
    rates: dict[str, float | None] = {"kernel_db_per_ns": rate_kernel,
                                      "engine_db_per_ns": (
                                          float(rate_engine_db_per_ns)
                                          if rate_engine_db_per_ns is not None
                                          else None)}
    used = [rate_kernel]
    if rates["engine_db_per_ns"] is not None:
        used.append(float(rates["engine_db_per_ns"]))
    rate_used = min(used)                            # 取慢者=保守长预测（上限语义）
    e_cap = float(e_cap_db)
    t_cap_end = done * dt
    if e_cap <= end_criteria_db:
        return {"converged_in_stage1": True, "dt_s": dt, "iterations_done": done,
                "excitation_steps": n_exc, "e_cap_db": e_cap,
                "t_cap_end_s": t_cap_end, "rates": rates, "rate_used_db_per_ns": None,
                "t_full_s": None, "nrts_pred": None, "nrts": None,
                "floor_steps": max(done, n_exc), "wall_per_step_s": None,
                "wall_pred_s": None, "budget_wall_s": None,
                "end_criteria_db": float(end_criteria_db)}
    delta_e_db = max(e_cap - end_criteria_db, 0.0)   # 距判据的能量余量（−13→−60 差 47dB）
    t_full = max(t_cap_end, n_exc * dt) + (delta_e_db / rate_used) * 1e-9
    nrts_pred = math.ceil(t_full / dt)
    floor = max(done, n_exc)
    nrts = max(math.ceil(safety_nrts * nrts_pred), floor)
    wall_per_step = (float(stage1_wall_s) / done
                     if stage1_wall_s is not None and float(stage1_wall_s) > 0 else None)
    wall_pred = wall_per_step * nrts_pred if wall_per_step is not None else None
    return {"converged_in_stage1": False, "dt_s": dt, "iterations_done": done,
            "excitation_steps": n_exc, "e_cap_db": e_cap, "t_cap_end_s": t_cap_end,
            "rates": rates, "rate_used_db_per_ns": rate_used, "t_full_s": t_full,
            "nrts_pred": nrts_pred, "nrts": nrts, "floor_steps": floor,
            "wall_per_step_s": wall_per_step, "wall_pred_s": wall_pred,
            "budget_wall_s": (safety_budget * wall_pred
                              if wall_pred is not None else None),
            "end_criteria_db": float(end_criteria_db)}


def blocked_check(template: str, elapsed_s: float,
                  last_energy_db: float | None) -> dict[str, Any]:
    """combline blocked 规则（criteria_a.md §四）：起跑 4h 后能量仍 >−10dB → blocked。

    其余模板不套用；能量读不到 = 不杀（观测缺失不触发不可逆动作，#105）。
    """
    if template != BLOCKED_TEMPLATE:
        return {"applicable": False, "blocked": False, "reason": "blocked 规则仅 combline"}
    if float(elapsed_s) < BLOCKED_AFTER_S:
        return {"applicable": True, "blocked": False,
                "reason": f"未到 {BLOCKED_AFTER_S / 3600:.0f}h 检查点"}
    if last_energy_db is None:
        return {"applicable": True, "blocked": False, "reason": "能量不可读（不杀）"}
    blocked = float(last_energy_db) > BLOCKED_ENERGY_MAX_DB
    reason = (f"4h 后能量 {last_energy_db:.1f}dB > {BLOCKED_ENERGY_MAX_DB}dB"
              if blocked else f"4h 后能量 {last_energy_db:.1f}dB ≤ {BLOCKED_ENERGY_MAX_DB}dB")
    return {"applicable": True, "blocked": blocked, "reason": reason}


def sentinel_gate(conf: dict[str, Any] | None,
                  s21_inf_f0_db: float | None) -> dict[str, Any]:
    """stage1 前哨门（criteria_a.md §三）：置信三面齐过 AND S21∞@f0 ≥ −3dB。

    S11∞ 语义切换：重设计后失配应已消除，S11∞ 降级为记录量不再进门。
    """
    conf_ok = bool(conf.get("ok", False)) if isinstance(conf, dict) else False
    reasons: list[str] = []
    if not conf_ok:
        if isinstance(conf, dict) and isinstance(conf.get("reasons"), list):
            reasons += [str(r) for r in conf["reasons"]]
        else:
            reasons.append("q_extrap 置信报告不可判读")
    s21_ok = False
    if s21_inf_f0_db is None or not math.isfinite(float(s21_inf_f0_db)):
        reasons.append("S21∞@f0 缺失（外推不可读）")
    else:
        s21_ok = float(s21_inf_f0_db) >= SENTINEL_S21_INF_F0_MIN_DB
        if not s21_ok:
            reasons.append(f"S21∞@f0 {s21_inf_f0_db:.2f}dB < "
                           f"{SENTINEL_S21_INF_F0_MIN_DB}dB（带心不在带内，重设计失效信号）")
    return {"ok": conf_ok and s21_ok, "conf_ok": conf_ok, "s21_inf_f0_db": s21_inf_f0_db,
            "s21_ok": s21_ok, "reasons": reasons,
            "thresholds": {"dev_db_max": Q_EXTRAP_DEV_DB_MAX,
                           "holdout_rel_max": Q_EXTRAP_HOLDOUT_REL_MAX,
                           "span_db_min": Q_EXTRAP_SPAN_DB_MIN,
                           "s21_inf_f0_min_db": SENTINEL_S21_INF_F0_MIN_DB}}


# ─── plan.json 三块（criteria_a.md §五，一次写入不可变）────────────────────────

def _plan_path(root: Path | None = None) -> Path:
    return (root or ROOT) / PLAN_NAME


def _plan_load(root: Path | None = None) -> dict[str, Any]:
    p = _plan_path(root)
    if not p.exists():
        raise FileNotFoundError(f"plan.json 不在档（先跑 --plan）：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _plan_write(plan: dict[str, Any], root: Path | None = None) -> None:
    _plan_path(root).write_text(
        json.dumps(plan, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _payload_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ka = {k: v for k, v in a.items() if k != "declared_utc"}
    kb = {k: v for k, v in b.items() if k != "declared_utc"}
    return ka == kb


def declare_block(template: str, name: str, payload: dict[str, Any],
                  root: Path | None = None) -> dict[str, Any]:
    """plan.json 的 stage1/stage2 声明块一次写入：已存在且 payload 等价（除时间戳）
    → 幂等无操作；不等价 → 拒绝（预声明不可变，#122；真机测量/预算不可事后换数）。"""
    plan = _plan_load(root)
    blocks = plan["templates"][template]
    existing = blocks.get(name)
    if existing is not None:
        if _payload_equal(existing, payload):
            return existing
        raise ValueError(
            f"plan[{template}][{name}] 已声明且不等价，拒绝改数（criteria_a.md §五；"
            "重开须主代理裁决留痕）\n"
            f"  在档: {json.dumps(existing, sort_keys=True, default=str)[:400]}\n"
            f"  新值: {json.dumps(payload, sort_keys=True, default=str)[:400]}")
    full = dict(payload)
    full["declared_utc"] = utc_now()
    blocks[name] = full
    _plan_write(plan, root)
    return full


def _refix_dt_reference(template: str) -> float | None:
    """refix 引擎日志实测 dt 对照（best-effort 观测性，#105：缺失不阻塞）。"""
    log = REPO / "runs" / "smoke_c3_refix" / template / "engine.log"
    if not log.exists():
        return None
    m = re.search(r"FDTD timestep is: ([0-9.eE+-]+) s",
                  log.read_text(encoding="utf-8", errors="replace"))
    return float(m.group(1)) if m else None


def _load_nominals_doc(nominals_path: Path | None = None) -> dict[str, Any]:
    """重设计名义 doc 装载（出处纪律：缺省=smoke_c3_redesign 存档；
    新批次经 nominals_path 指向当轮 redesign_nominals.json——防陈旧档误读）。"""
    path = Path(nominals_path) if nominals_path is not None else NOMINALS_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _nominal_matches_redesign(template: str, nominal: dict[str, Any],
                              doc: dict[str, Any] | None = None) -> bool:
    """TEMPLATE_NOMINAL 与重设计名义 new_nominal 的 4 位舍入一致性。

    doc 缺省装载 NOMINALS_PATH 存档；传入当轮 doc（_load_nominals_doc 产物）
    时按当轮校验（R2：名义注册批次显式化，防跨批次陈旧比对）。
    """
    new_nom = (doc or _load_nominals_doc())["templates"][template]["new_nominal"]
    for key, want in new_nom.items():
        got = nominal.get(key)
        if isinstance(want, list):
            mine = [round(float(v), 4) for v in got or []]
            theirs = [round(float(v), 4) for v in want]
            if mine != theirs:
                return False
        elif isinstance(want, (int, float)) and not isinstance(want, bool):
            if round(float(got), 4) != round(float(want), 4):
                return False
        elif got != want:
            return False
    return True


def plan_base_for(template: str, nominals_path: Path | None = None) -> dict[str, Any]:
    """单模板基座（离线，秒级）：重设计名义 + exec 几何段实测网格 + dt CFL 估计。

    dt_est = 1/(c0·sqrt(Σ 1/h_min²))（h_min=逐轴相邻网格线最小间距）；#312 已知
    实测/估计比 0.93-1.07 漂（sir_bpf 0.825 实证）——只作参考，权威 dt =
    stage1 引擎日志。激励时长三模板实测同值（网格无关）→ 激励步数估计 =
    NrTS 物理下限估计。
    nominals_path=R2 当轮名义 doc（缺省 smoke_c3_redesign 存档，行为不变）。
    """
    nominal = dict(TEMPLATE_NOMINAL[template])
    mesh_mm = auto_mesh_mm(template, nominal)
    mesh_max_mm = c3_mesh_max_mm(template, nominal)
    text = render_script(template, nominal, FREQ_RANGE_GHZ,
                         mesh_resolution_mm=mesh_mm)
    cut = text.find("# ── 求解 ──")
    head = text[:cut] if cut >= 0 else text[:text.index("FDTD.Run(")]
    scope: dict[str, Any] = {"__name__": "__main__",
                             "__file__": str(REPO / "_c3_fullcurve_plan_sim.py")}
    exec(compile(head, "c3_fullcurve_plan", "exec"), scope)   # 几何段（FDTD.Run 之前）
    grid: dict[str, Any] = {}
    h_min: list[float] = []
    for ax in ("x", "y", "z"):
        lines = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        gaps = np.diff(lines)                            # GetLines 口径：米
        grid[f"n_{ax}"] = int(lines.size)
        grid[f"min_gap_mm_{ax}"] = float(gaps.min()) * 1e3
        grid[f"min_gap_um_{ax}"] = float(gaps.min()) * 1e6
        h_min.append(float(gaps.min()))
    grid["n_cells"] = int(grid["n_x"] * grid["n_y"] * grid["n_z"])
    # 最小间距守卫（#152 家族：nm 级近重合线 → CFL 塌缩，起跑前离线可判）
    grid["min_gap_um_all"] = float(min(grid[f"min_gap_um_{ax}"] for ax in ("x", "y", "z")))
    dt_est = 1.0 / (_C0 * math.sqrt(sum(1.0 / h ** 2 for h in h_min)))
    n_exc_est = math.ceil(T_EXCITE_REF_S / dt_est)
    dt_ref = _refix_dt_reference(template)
    return {"template": template, "nominal": nominal, "mesh_mm": mesh_mm,
            "mesh_max_mm": mesh_max_mm,
            "mesh_source": "auto c3_mesh_max_mm（NEAR≤缝_min/3，#266）向下取整到 µm",
            "grid": grid, "dt_cfl_estimate_s": dt_est,
            "dt_refix_reference_s": dt_ref,
            "dt_est_vs_ref_ratio": (round(dt_ref / dt_est, 4)
                                    if dt_ref is not None else None),
            "t_excite_ref_s": T_EXCITE_REF_S,
            "n_excitation_steps_est": n_exc_est,
            "nrts_floor_estimate": n_exc_est,
            "nominal_matches_redesign": _nominal_matches_redesign(
                template, nominal,
                _load_nominals_doc(nominals_path)
                if nominals_path is not None else None),
            "nominals_path": (str(nominals_path) if nominals_path is not None
                              else str(NOMINALS_PATH)),
            "old_design_reference": OLD_DESIGN_REFERENCE.get(template),
            "old_design_reference_note": (
                "旧（失配）设计实测对照列——衰减动力学随失配消除而变，禁作新设计 "
                "NrTS/预算输入（criteria_a.md §〇）"),
            "stage1": None, "stage2": None}


def build_plan(root: Path | None = None, force: bool = False,
               nominals_path: Path | None = None) -> tuple[dict[str, Any], bool]:
    """--plan：三模板基座落盘（一次写入；已存在且非 force → 幂等跳过）。

    名义一致性硬校验 fail-closed（TEMPLATE_NOMINAL ≠ 重设计名义即退出——禁混用
    设计口径，criteria_a.md §五）。nominals_path=R2 当轮名义 doc（缺省
    smoke_c3_redesign 存档，行为不变）。
    """
    target = _plan_path(root)
    if target.exists() and not force:
        print(f"[plan] 已在档跳过（不可变；覆盖须 --force-plan 主代理裁决）：{target}")
        return json.loads(target.read_text(encoding="utf-8")), False
    templates: dict[str, Any] = {}
    for t in sorted(C3_TEMPLATES):
        base = plan_base_for(t, nominals_path=nominals_path)
        if not base["nominal_matches_redesign"]:
            raise ValueError(f"[{t}] TEMPLATE_NOMINAL ≠ redesign_nominals.json "
                             "new_nominal（4 位舍入）——禁混用设计口径，fail-closed"
                             "（criteria_a.md §五）")
        templates[t] = base
        g = base["grid"]
        print(f"[{t}] mesh={base['mesh_mm']}mm grid={g['n_x']}x{g['n_y']}x{g['n_z']} "
              f"({g['n_cells']:.3e} cells) min_gap={g['min_gap_um_all']:.1f}µm "
              f"dt_est={base['dt_cfl_estimate_s']:.4e}s"
              f"（vs refix 实测比 {base['dt_est_vs_ref_ratio']}）"
              f" n_exc_est={base['n_excitation_steps_est']}", flush=True)
    plan = {"batch": "smoke_c3_fullcurve", "criteria": CRITERIA_A,
            "generated_utc": utc_now(),
            "nominal_source": "TEMPLATE_NOMINAL（=重设计名义 4 位舍入，"
                              "redesign_nominals.json matches_registered_nominal=true）",
            "safety": {"nrts": SAFETY_NRTS, "budget": SAFETY_BUDGET,
                       "stage1_timeout_s": STAGE1_TIMEOUT_S,
                       "end_criteria_db": END_CRITERIA_DB},
            "immutability": "base 一次写入后不可变；stage1/stage2 声明块各一次写入"
                            "（payload 等价幂等，不等价拒绝）",
            "templates": templates}
    target.parent.mkdir(parents=True, exist_ok=True)
    _plan_write(plan, root)
    print(f"[plan] 基座落盘：{target}（判据 {CRITERIA_A}）")
    return plan, True


# ─── 命令构造与进程面（真机层，测试注入 mock）──────────────────────────────────

def stage_cmd(template: str, stage: str, timeout_s: float,
              nrts: int | None = None, root: Path | None = None) -> list[str]:
    """smoke CLI 调用命令（只参数化既有 CLI 面，不改源）。

    stage1：--q-extrap --timeout 5040（NrTS 缺省 1e6 不触顶，帽由 timeout 保证）；
    stage2：--nrts <N> --timeout <预算帽+600>；两阶段均**不传 --end-criteria**
    （EndCriteria 保持引擎缺省 −60dB 不动，criteria_a.md §一）。
    """
    cmd = [sys.executable, str(SMOKE_SCRIPT),
           "--template", template,
           "--root", str((root or ROOT).resolve()),
           "--pt", f"{template}/{stage}",
           "--q-extrap",
           "--timeout", repr(float(timeout_s))]
    if stage == "stage2":
        if nrts is None:
            raise ValueError("stage2 须给 nrts（plan 预声明后执行）")
        cmd += ["--nrts", str(int(nrts))]
    elif nrts is not None:
        raise ValueError("stage1 不接受 nrts（帽由 timeout 保证）")
    assert "--end-criteria" not in cmd, "EndCriteria 不许改写（引擎缺省 −60dB）"
    return cmd


def _pid_alive(pid: int) -> bool | None:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True, timeout=30)
        return str(pid) in (out.stdout or "")
    except Exception:
        return None


def acquire_lock(task: str, lock_path: Path | None = None,
                 poll_s: float = LOCK_POLL_S) -> int:
    """O_CREAT|O_EXCL 原子建锁；占用则轮询，pid 陈锁核验接管（factory_m3_valley 先例）。"""
    path = lock_path or _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"task": task, "ts": datetime.now(timezone.utc).isoformat(),
                       "pid": os.getpid()}
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            os.close(fd)
            return os.getpid()
        except FileExistsError:
            holder: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                holder = json.loads(path.read_text(encoding="utf-8"))
            pid = holder.get("pid")
            alive = _pid_alive(pid) if isinstance(pid, int) else None
            if alive is False:
                print(f"[lock] 陈锁接管（持有者 pid={pid} 已死）：{holder}", flush=True)
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            print(f"[lock] 锁被占（{holder or '未知持有者'}），{poll_s:.0f}s 后重试…",
                  flush=True)
            time.sleep(poll_s)


def release_lock(owner_pid: int, lock_path: Path | None = None) -> None:
    """删锁（删前校验 pid=自身，防误删后到者锁；best-effort #105）。"""
    path = lock_path or _lock_path()
    try:
        holder = json.loads(path.read_text(encoding="utf-8"))
        if holder.get("pid") == owner_pid:
            path.unlink()
    except Exception:
        pass


def oe_foreign_running(root: Path | None = None) -> list[str]:
    """#261 互斥查：python CommandLine 含 _rfauto_runner|simulation.py（fail-closed）。

    临时 .ps1 经 powershell -NoProfile -ExecutionPolicy Bypass -File（#289：
    内联 $_ 会被 shell 层展开/引号嵌套不可过）。
    """
    base = root or ROOT
    base.mkdir(parents=True, exist_ok=True)
    ps1 = base / "_oe_proc_check.ps1"
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


def kill_tree(pid: int) -> None:
    """taskkill /F /T /PID（python 列表参数无 MSYS 转换，#245 家族；best-effort）。"""
    with contextlib.suppress(Exception):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(int(pid))],
                       capture_output=True, timeout=60)


def last_engine_energy(work: Path) -> float | None:
    """engine.log 末段能量 dB（tail 读取；blocked watch / 帽停快照用，#268 不看 mtime）。"""
    log = work / "engine.log"
    if not log.exists():
        return None
    tail = ""
    with contextlib.suppress(OSError), open(log, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        fh.seek(max(0, fh.tell() - 65536))
        tail = fh.read().decode("utf-8", errors="replace")
    hits = _RE_PROG.findall(tail)
    return float(hits[-1][2]) if hits else None


def port_ut_tail_seconds(work: Path) -> float | None:
    """port_ut_1B 末行时间轴（帽停快照，#328 真实进度证据）。"""
    for cand in (work / "fdtd", work / "fdtd_partial"):
        p = cand / "port_ut_1B"
        if not p.exists():
            continue
        with contextlib.suppress(OSError):
            with open(p, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - 8192))
                text = fh.read().decode("utf-8", errors="replace")
            rows = [ln for ln in text.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("%")]
            if rows:
                return float(rows[-1].split()[0])
    return None


def _launch_stage1_real(cmd: list[str], timeout_s: float, cwd: Path) -> dict[str, Any]:
    """真机 stage1 发射（本 runner 自身由主代理 Start-Process 分离托管）。

    帽 = smoke 自身 --timeout（其内部 subprocess.run 超时先杀引擎孙进程）；
    runner 侧 timeout 只兜底挂死。elapsed_s = 帽停/秒退分类依据
    （classify_stage1_outcome：≥STAGE1_CAPSTOP_MIN_S 判帽停非 crash）。
    """
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout_s)
        return {"rc": proc.returncode, "killed": None, "elapsed_s": time.time() - t0,
                "stdout_tail": (proc.stdout or "")[-2000:],
                "stderr_tail": (proc.stderr or "")[-2000:]}
    except subprocess.TimeoutExpired:
        return {"rc": None, "killed": "runner_deadline",
                "elapsed_s": time.time() - t0, "stdout_tail": "",
                "stderr_tail": ""}


def classify_stage1_outcome(outcome: dict[str, Any],
                            cap_min_s: float = STAGE1_CAPSTOP_MIN_S,
                            ) -> dict[str, Any]:
    """stage1 发射结局分类（纯函数）：ok / capstop / quick_exit。

    帽停形态 = smoke 自身 --timeout 杀引擎后 TimeoutExpired 未捕获崩溃退出
    （rc=1，已运行 ≈ 帽值 5040s）或 runner 侧终极守卫触发（killed=
    runner_deadline，必然已等满 5040+900s）——共同特征 = 已运行 ≥
    STAGE1_CAPSTOP_MIN_S（部分产物值得判读）；不足下限 = 秒退 crash。
    """
    rc = outcome.get("rc")
    killed = outcome.get("killed")
    elapsed = outcome.get("elapsed_s")
    if rc == 0 and not killed:
        return {"kind": "ok", "capstop": False, "rc": rc, "killed": None,
                "elapsed_s": elapsed}
    ran_long = elapsed is not None and float(elapsed) >= float(cap_min_s)
    if ran_long or killed == "runner_deadline":
        return {"kind": "capstop", "capstop": True, "rc": rc, "killed": killed,
                "elapsed_s": elapsed}
    return {"kind": "quick_exit", "capstop": False, "rc": rc, "killed": killed,
            "elapsed_s": elapsed}


def _sanitize_probe_dir(work: Path) -> Path | None:
    """fdtd/ 探针 → fdtd_partial/（剔除被 kill 截断的残行；refix 轮
    extract_partial.py prepare_partial_dir 同式收敛进 runner，归档目录零改写）。

    fdtd_partial/ 已在档（先前归档）→ 不覆盖返回 None；无可解析数据行 → None。
    """
    src = work / "fdtd"
    dst = work / "fdtd_partial"
    if not src.is_dir() or dst.exists():
        return None
    n_files = 0
    for p in sorted(src.iterdir()):
        if not p.name.startswith(("port_ut_", "port_it_")):
            continue
        header: list[str] = []
        rows: list[str] = []
        ncol: int | None = None
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("%"):
                header.append(line)
                continue
            parts = line.split()
            if not parts:
                continue
            if ncol is None:
                ncol = len(parts)
            if len(parts) != ncol:
                continue                       # kill 截断残行
            try:
                [float(v) for v in parts]
            except ValueError:
                continue
            rows.append(line)
        if not rows:
            continue
        (dst / p.name).parent.mkdir(parents=True, exist_ok=True)
        (dst / p.name).write_text("\n".join(header + rows) + "\n", encoding="utf-8")
        n_files += 1
    return dst if n_files else None


def _span_rerun_hint(summary: dict[str, Any]) -> dict[str, Any] | None:
    """span 缺口的加窗估计（只记录不进门）：kernel span_db=8.686·α·窗时长，
    最弱模再衰 Δspan 需环振窗再加 ΔT=Δspan/(8.686·α_weakest)。"""
    conf = summary.get("confidence")
    if not isinstance(conf, dict) or conf.get("ok"):
        return None
    checks = conf.get("checks") or {}
    span_obs = checks.get("span_db_min_obs")
    span_min = checks.get("span_db_min")
    modes = summary.get("q_extrap_modes") or []
    if not (isinstance(span_obs, (int, float)) and isinstance(span_min, (int, float))
            and isinstance(modes, list) and modes):
        return None
    weakest = min(modes, key=lambda m: float(m.get("span_db", float("inf"))))
    alpha = float(weakest.get("alpha_per_ns") or 0.0)
    if not (alpha > 0.0 and math.isfinite(alpha)):
        return {"note": "最弱模 α≈0（零衰减伪模/拟合退化）——加窗估计无意义，"
                        "span 门不过为主（单纯加帽窗未必可辨）"}
    extra_ns = (float(span_min) - float(span_obs)) / (8.686 * alpha)
    if extra_ns <= 0.0:
        return None
    if extra_ns > 1e6:
        # ≥1ms 量级环振窗 = FDTD 不可达 → α_weakest 实为近零衰减伪模/拟合退化
        return {"note": f"最弱模 α 退化（ΔT 估计 {extra_ns:.3g}ns 不可达）——span 门"
                        "不过为主，单纯加帽窗无可辨收益（只记录不进门）",
                "basis": "Δspan/(8.686·α_weakest) 上溢：α_weakest≈0"}
    hint: dict[str, Any] = {"extra_ringdown_ns": round(extra_ns, 1),
                            "weakest_mode_ghz": round(float(weakest["f0_ghz"]), 4),
                            "basis": "Δspan/(8.686·α_weakest)，kernel span 口径"}
    dt = (summary.get("engine") or {}).get("dt_s")
    if dt:
        hint["extra_steps_est"] = math.ceil(extra_ns * 1e-9 / float(dt))
    hint["note"] = ("帽窗须 ≈ 激励 + 环振(现窗+ΔT)+fit 余量——按此评估加帽重跑是否值得"
                    "（只记录不进门）")
    return hint


def stage1_partial_verdict(template: str, root: Path | None = None,
                           outcome: dict[str, Any] | None = None,
                           summary: dict[str, Any] | None = None,
                           cap_s: float | None = None,
                           ) -> dict[str, Any]:
    """stage1 帽停/崩溃结局 → 部分产物判读 verdict（stage1/stage1_verdict.json，
    离线可重放；--judge-stage1 即本函数纯离线重放）。

    cap_s=发射帽秒落痕（2①）：run_stage1 显式传入；离线重放缺省从 summary
    取在档 stage1_cap_s，全无凭据如实 None（不臆造）。

    帽 = 防挂死非预算门（criteria_a §一）：引擎被 --timeout 杀死后的 port_ut/et
    流式部分产物照样判读——kernel ringdown 提取 + 置信三门 + S21∞@f0 门（门数值
    不动，§三；帽窗 < s21_f0 min_duration 属预期，判读主路径=置信门内 ringdown
    外推）。数据不足（激励未完成/环振段缺失/q_extrap 不可判）→ 如实 FAIL 写明
    缺什么（不凑绿 #122）；秒退 = crash 如实 FAIL 不判读。PASS 附实测衰减率与
    stage2 NrTS 预声明值（compute_stage2_plan 公式；发射归主代理）。
    """
    work = stage_dir(template, "stage1", root)
    cls = (classify_stage1_outcome(outcome) if outcome is not None else
           {"kind": "offline_replay", "capstop": None, "rc": None,
            "killed": None, "elapsed_s": None})
    doc: dict[str, Any] = {"template": template, "stage": "stage1",
                           "criteria": CRITERIA_A, "classification": cls,
                           "generated_utc": utc_now()}
    if cls["kind"] == "quick_exit":
        doc.update({"basis": "crash", "verdict": "FAIL", "fail_kind": "crash",
                    "data": None, "confidence": None, "sentinel": None,
                    "rates": None, "stage2_plan": None, "rerun_hint": None,
                    "stage1_cap_s": (float(cap_s) if cap_s is not None else None),
                    "reasons": [f"引擎秒退（rc={cls['rc']}, "
                                f"elapsed={cls['elapsed_s']}s < "
                                f"{STAGE1_CAPSTOP_MIN_S:.0f}s 帽停下限）——crash "
                                "如实 FAIL，不走部分产物判读"]})
        work.mkdir(parents=True, exist_ok=True)
        (work / STAGE1_VERDICT_NAME).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        return doc
    if summary is None:
        summary = summarize_stage1(template, root)
    # fdtd/ 探针被 kill 截断残行打不进内核 → 剔残行归档 fdtd_partial/
    # （refix extract_partial 同式，归档零改写）后按 sanitized 目录重放
    try:
        load_msl_probes(str(work / "fdtd"))
    except Exception:
        alt = _sanitize_probe_dir(work)
        if alt is not None:
            summary = summarize_stage1(template, root, probe_dir=alt)
    eng = summary.get("engine") or {}
    sent = summary.get("sentinel") or {}
    conf = summary.get("confidence")
    t_exc = eng.get("excitation_s")
    dt = eng.get("dt_s")
    steps = eng.get("last_progress_step")
    t_end_probe = port_ut_tail_seconds(work)
    data_reasons: list[str] = []
    if t_exc is None or dt is None:
        data_reasons.append("engine.log 缺 excitation_s/dt_s（头部信息缺失，#122 不采信）")
    if t_end_probe is None:
        data_reasons.append("探针时间轴不可读（port_ut_1B 缺失或无数据行）")
    elif t_exc is not None and t_end_probe < float(t_exc):
        data_reasons.append(
            f"探针窗 {t_end_probe * 1e9:.2f}ns < 激励时长 {float(t_exc) * 1e9:.2f}ns"
            "（激励未完成即帽停，环振段不存在——同帽重跑无改善）")
    if summary.get("q_extrap_error"):
        data_reasons.append(f"q_extrap 内核不可判读：{summary['q_extrap_error']}")
    rate_kernel = summary.get("rate_kernel_db_per_ns")
    rate_engine = summary.get("rate_engine_db_per_ns")
    rates_avail = [float(r) for r in (rate_kernel, rate_engine) if r is not None]
    rates = {"kernel_db_per_ns": rate_kernel, "engine_db_per_ns": rate_engine,
             "rate_used_db_per_ns": (min(rates_avail) if rates_avail else None)}
    doc["data"] = {"t_excite_ns": (float(t_exc) * 1e9 if t_exc is not None else None),
                   "probe_t_end_ns": (t_end_probe * 1e9
                                      if t_end_probe is not None else None),
                   "cap_steps": steps, "e_cap_db": eng.get("last_energy_db"),
                   "dt_s": dt, "excitation_steps": eng.get("excitation_steps")}
    doc["confidence"] = conf
    doc["sentinel"] = sent
    doc["rates"] = rates
    if summary.get("spurious") is not None:          # 伪模判别留痕
        doc["spurious"] = {k: v for k, v in summary["spurious"].items()
                           if k != "report_physical"}
    verdict_pass = not data_reasons and bool(sent.get("ok"))
    stage2_plan: dict[str, Any] | None = None
    if verdict_pass:
        need = {"cap_steps": steps, "e_cap_db": eng.get("last_energy_db"),
                "dt_s": dt, "excitation_steps": eng.get("excitation_steps"),
                "alpha_min_per_ns": summary.get("alpha_min_per_ns")}
        missing = sorted(k for k, v in need.items() if v is None)
        if missing:
            verdict_pass = False
            data_reasons.append("前哨门过但 stage2 NrTS 输入缺失：" + "、".join(missing))
        else:
            wall_s = (float(outcome["elapsed_s"])
                      if outcome is not None and outcome.get("elapsed_s") is not None
                      else None)
            stage2_plan = compute_stage2_plan(
                dt_s=float(dt), iterations_done=int(steps),
                excitation_steps=int(eng["excitation_steps"]),
                e_cap_db=float(eng["last_energy_db"]),
                alpha_min_per_ns=float(summary["alpha_min_per_ns"]),
                rate_engine_db_per_ns=rate_engine, stage1_wall_s=wall_s)
    reasons = list(data_reasons)
    if not verdict_pass and not data_reasons:
        reasons += [str(r) for r in sent.get("reasons", [])]
    doc["stage2_plan"] = stage2_plan
    doc["rerun_hint"] = (_span_rerun_hint(summary) if not verdict_pass else None)
    if cap_s is not None:
        doc["stage1_cap_s"] = float(cap_s)
    else:
        doc["stage1_cap_s"] = (summary or {}).get("stage1_cap_s")
    doc.update({"basis": ("capstop" if cls["kind"] == "capstop"
                          else "offline_replay"),
                "verdict": "PASS" if verdict_pass else "FAIL",
                "fail_kind": (None if verdict_pass else
                              ("insufficient_data" if data_reasons else "gates")),
                "reasons": reasons})
    (work / STAGE1_VERDICT_NAME).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return doc


def _launch_stage2_real(cmd: list[str], work: Path, template: str, timeout_s: float,
                        budget_s: float, cwd: Path,
                        poll_s: float = WATCH_POLL_S) -> dict[str, Any]:
    """真机 stage2 发射：Popen + 轮询（combline blocked 4h 能量面 + 终极挂死守卫）。

    smoke 内部 --timeout = 预算硬帽+600 先杀引擎（正常帽停路径）；runner 侧
    blocked/deadline 走 taskkill /F /T 杀树（#245 家族：python 列表参数）。
    """
    work.mkdir(parents=True, exist_ok=True)
    runner_log = work / "runner_stage2.log"
    with open(runner_log, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=log,
                                stderr=subprocess.STDOUT)
    start = time.time()
    while True:
        rc = proc.poll()
        if rc is not None:
            return {"rc": int(rc), "killed": None}
        elapsed = time.time() - start
        if elapsed > timeout_s:                       # 终极挂死守卫（正常到不了）
            kill_tree(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=120)
            return {"rc": None, "killed": "runner_deadline"}
        chk = blocked_check(template, elapsed, last_engine_energy(work))
        if chk["blocked"]:
            print(f"[stage2] blocked：{chk['reason']}，杀树上报", flush=True)
            kill_tree(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=120)
            return {"rc": None, "killed": "blocked",
                    "blocked_reason": chk["reason"]}
        time.sleep(poll_s)


# ─── stage1：前哨摘要（判读层，离线可重放）─────────────────────────────────────

def _prior_stage1_cap(work: Path) -> float | None:
    """在档 summary 的 stage1_cap_s（离线重放保留原 run 落痕；#105 缺失/损坏
    如实 None，不臆造）。"""
    p = work / "_stage1_summary.json"
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8")).get("stage1_cap_s")
        return float(v) if v is not None else None
    except Exception:
        return None


def summarize_stage1(template: str, root: Path | None = None,
                     probe_dir: Path | None = None,
                     cap_s: float | None = None) -> dict[str, Any]:
    """stage1 产物 → 前哨摘要（engine.log + fdtd 探针；同输入幂等可重放）。

    probe_dir 显式给定时覆盖缺省解析（帽停 sanitized fdtd_partial/ 重放用，
    剔 kill 残行后 fdtd/ 原目录打不进内核的场景）。
    cap_s=stage1 帽秒落痕（2①：缺省 5040 也显式落，防"生效值不落痕"）——
    发射路径由 run_stage1 显式传入；离线重放无此信息时取在档 summary 的
    stage1_cap_s 保留原 run 落痕，全无凭据时按缺省帽值 STAGE1_TIMEOUT_S 注记。
    """
    work = stage_dir(template, "stage1", root)
    log_path = work / "engine.log"
    if not log_path.exists():
        return {"template": template, "stage": "stage1", "verdict": "SUMMARIZE_FAIL",
                "reasons": [f"缺 engine.log：{work}"]}
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    eng = parse_engine_log(log_text)
    t_exc = eng.get("excitation_s")
    dt = eng.get("dt_s")
    reasons: list[str] = []
    qrep: dict[str, Any] = {"error": "skip"}
    conf: dict[str, Any] | None = None
    s21_inf_f0_db: float | None = None
    alpha_min: float | None = None
    split_doc: dict[str, Any] | None = None
    if t_exc is None or dt is None:
        reasons.append("engine.log 缺 excitation_s/dt_s（终止信息缺失，#122 不采信）")
    else:
        pdir = probe_dir or _probe_dir(work)
        if pdir is None:
            reasons.append(f"无探针文件（{work} 下缺 port_ut_1B）")
        else:
            freq = np.linspace(FREQ_RANGE_GHZ[0] * 1e9, FREQ_RANGE_GHZ[1] * 1e9, N_FREQ)
            qrep = q_extrap_report_from_probes(str(pdir), freq, float(t_exc),
                                               F0_GHZ * 1e9)
            # 伪模判别：材料 Q 帽以上非器件模 → 物理模基重外推；
            # 无伪模 split=None → 以下逐字节走原路径（缺省不变铁律）
            if "keys" in qrep:
                split_doc = split_physical_refit(str(pdir), freq, float(t_exc),
                                                 F0_GHZ * 1e9,
                                                 qrep.get("modes") or [])
            if split_doc is not None:
                if not split_doc["physical"]:
                    reasons.append("全部模式材料 Q 帽判伪（物理模缺失）——伪模不进"
                                   "收敛门/尾外推基，如实 FAIL")
                elif not split_doc["refit_ok"]:
                    reasons.append("物理模基重外推不可判读（保留全模报告，如实 FAIL）")
                else:
                    qrep = split_doc["report_physical"]
            if "keys" not in qrep:
                reasons.append(f"q_extrap 报告不可判读：{qrep.get('error')}")
            else:
                conf = q_extrapolation_gate(qrep)
                keys = qrep["keys"]
                if isinstance(keys.get("s21_f0"), dict):
                    s21_inf_f0_db = float(keys["s21_f0"]["s_inf_db"])
                modes = qrep.get("modes") or []
                if modes:
                    alpha_min = min(float(m["alpha_per_ns"]) for m in modes)
                else:
                    reasons.append("环振模式表为空（α 不可辨识）")
    rate_engine = (engine_energy_tail_rate(log_text, float(dt), float(t_exc))
                   if t_exc is not None and dt is not None else None)
    sent = sentinel_gate(conf, s21_inf_f0_db)
    if cap_s is not None:
        cap_recorded: float | None = float(cap_s)
    else:
        prior_cap = _prior_stage1_cap(work)
        cap_recorded = (prior_cap if prior_cap is not None
                        else float(STAGE1_TIMEOUT_S))
    summary: dict[str, Any] = {
        "template": template, "stage": "stage1", "criteria": CRITERIA_A,
        "engine": eng, "q_extrap_error": qrep.get("error"),
        "stage1_cap_s": cap_recorded,
        "q_extrap_modes": qrep.get("modes"),
        "q_extrap_keys": {k: {kk: vv for kk, vv in v.items()
                              if kk in ("freq_hz", "s_trunc_db", "s_inf_db", "dev_db",
                                        "holdout_rel", "resid_rel", "min_duration_s",
                                        "min_duration_satisfied")}
                          for k, v in (qrep.get("keys") or {}).items()},
        "confidence": conf, "alpha_min_per_ns": alpha_min,
        "rate_kernel_db_per_ns": (energy_rate_from_alpha(alpha_min)
                                  if alpha_min is not None else None),
        "rate_engine_db_per_ns": rate_engine,
        "sentinel": sent,
        "verdict": ("SENTINEL_PASS" if sent["ok"] else "SENTINEL_FAIL"),
        "reasons": reasons + list(sent["reasons"]),
        "generated_utc": utc_now(),
    }
    if split_doc is not None:                        # 伪模在场才记录（缺省零新增键）
        summary["spurious"] = split_doc
    (work / "_stage1_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return summary


def _stage1_payload(summary: dict[str, Any]) -> dict[str, Any]:
    eng = summary.get("engine") or {}
    # 帽停容忍（#323 族）：被杀轮无终止行（iterations_done 缺失）→ 步数锚取
    # 末进度行 last_progress_step、E_cap 取末点能量（帽停锚 = 杀死时刻状态，
    # criteria_a §二 t_cap_end/ΔE 口径）；自然停轮维持原口径（min_energy）。
    natural = eng.get("iterations_done") is not None
    steps = eng.get("iterations_done") if natural else eng.get("last_progress_step")
    e_cap = eng.get("min_energy_db") if natural else eng.get("last_energy_db")
    return {"alpha_min_per_ns": summary.get("alpha_min_per_ns"),
            "rate_kernel_db_per_ns": summary.get("rate_kernel_db_per_ns"),
            "rate_engine_db_per_ns": summary.get("rate_engine_db_per_ns"),
            "e_cap_db": e_cap,
            "iterations_done": steps,
            "steps_source": ("engine_done" if natural
                             else "last_progress_step(capstop)"),
            "dt_s": eng.get("dt_s"),
            "excitation_steps": eng.get("excitation_steps"),
            "solve_s": eng.get("engine_wall_s"),
            "sentinel_ok": bool((summary.get("sentinel") or {}).get("ok", False)),
            "verdict": summary.get("verdict"),
            "stage1_verdict": ((summary.get("stage1_verdict") or {}).get("verdict"))}


# ─── stage1/stage2 编排（真机层可注入 mock；断点续跑幂等）───────────────────────

def run_stage1(template: str, root: Path | None = None,
               launch_fn: Callable[[list[str], float, Path], dict[str, Any]] | None = None,
               guard: Callable[[], list[str]] | None = None,
               cap_s: float = STAGE1_TIMEOUT_S) -> dict[str, Any]:
    """stage1 编排：完成标记在档 → 跳过（断点续跑幂等）；否则锁内 #261 查 + 发射
    + 摘要 + stage1 声明块落盘。结局三分：ok=前哨门定 SENTINEL_*；帽停（elapsed
    ≥ STAGE1_CAPSTOP_MIN_S）=部分产物判读产 stage1_verdict.json；秒退=crash
    如实 FAIL。前哨/判读 FAIL → rc 语义 1（不放行 stage2）。"""
    work = stage_dir(template, "stage1", root)
    summary_path = work / "_stage1_summary.json"
    if summary_path.exists():
        print(f"[stage1:{template}] 已完成（{summary_path} 在档），跳过（断点续跑）",
              flush=True)
        return json.loads(summary_path.read_text(encoding="utf-8"))
    launch = launch_fn or _launch_stage1_real
    check = guard or oe_foreign_running
    foreign = check()
    if foreign:
        return {"template": template, "verdict": "REFUSED",
                "reasons": [f"#261 互斥：检测到在跑 openEMS 进程：{foreign}"]}
    lock_path = _lock_path(root)
    owner = acquire_lock(f"c3_fullcurve_stage1/{template}", lock_path)
    try:
        work.mkdir(parents=True, exist_ok=True)
        cmd = stage_cmd(template, "stage1", cap_s, root=root)
        print(f"[stage1:{template}] 发射：{' '.join(cmd)}", flush=True)
        cwd = REPO if root is None else Path(root)
        outcome = launch(cmd, cap_s + STAGE1_RUNNER_MARGIN_S, cwd)
        print(f"[stage1:{template}] 引擎结束：{json.dumps(outcome, ensure_ascii=False)}",
              flush=True)
        summary = summarize_stage1(template, root, cap_s=cap_s)
        if classify_stage1_outcome(outcome)["kind"] != "ok":
            # 帽停容忍（criteria_a §一 帽=防挂死非预算门）：帽停 → 部分产物判读
            # 产 stage1_verdict.json；秒退 → crash FAIL。门数值不动（§三）。
            summary["stage1_verdict"] = stage1_partial_verdict(
                template, root, outcome=outcome, summary=summary, cap_s=cap_s)
        plan = _plan_load(root)
        if (plan["templates"][template] or {}).get("stage1") is None:
            declare_block(template, "stage1", _stage1_payload(summary), root)
        return summary
    finally:
        release_lock(owner, lock_path)


def run_stage2(template: str, root: Path | None = None,
               launch_fn: Callable[..., dict[str, Any]] | None = None,
               guard: Callable[[], list[str]] | None = None) -> dict[str, Any]:
    """stage2 编排：前哨 PASS 才放行；NrTS 先写 plan 声明块再发射（预声明后执行，
    断点重入复用已声明 NrTS 不重算）；结束后帽停快照（如需）+ 全曲线判读。"""
    work = stage_dir(template, "stage2", root)
    judged = work / "_judge_a.json"
    if judged.exists():
        print(f"[stage2:{template}] 已判读（{judged} 在档），跳过（断点续跑）",
              flush=True)
        return json.loads(judged.read_text(encoding="utf-8"))
    plan = _plan_load(root)
    blocks = plan["templates"][template] or {}
    s1 = blocks.get("stage1")
    if s1 is None:
        summary = summarize_stage1(template, root)
        if summary.get("verdict") == "SUMMARIZE_FAIL":
            return summary
        s1 = declare_block(template, "stage1", _stage1_payload(summary), root)
    if not s1.get("sentinel_ok", False):
        return {"template": template, "verdict": "REFUSED",
                "reasons": [f"stage1 前哨未 PASS（verdict={s1.get('verdict')}），"
                            "stage2 不放行，上报裁决（criteria_a.md §三）"]}
    s2 = blocks.get("stage2")
    if s2 is None:
        computed = compute_stage2_plan(
            dt_s=float(s1["dt_s"]), iterations_done=int(s1["iterations_done"]),
            excitation_steps=int(s1["excitation_steps"]),
            e_cap_db=float(s1["e_cap_db"]),
            alpha_min_per_ns=float(s1["alpha_min_per_ns"]),
            rate_engine_db_per_ns=s1.get("rate_engine_db_per_ns"),
            stage1_wall_s=s1.get("solve_s"))
        if computed["converged_in_stage1"]:
            declare_block(template, "stage2",
                          {"converged_in_stage1": True, "nrts": None,
                           "skip_reason": "stage1 帽内已自然收敛，stage1 即全曲线"},
                          root)
            return judge_fullcurve_stage1_as_full(template, root)
        s2 = declare_block(template, "stage2", {
            "nrts": computed["nrts"], "nrts_pred": computed["nrts_pred"],
            "floor_steps": computed["floor_steps"],
            "rate_used_db_per_ns": computed["rate_used_db_per_ns"],
            "rates": computed["rates"], "t_full_s": computed["t_full_s"],
            "t_cap_end_s": computed["t_cap_end_s"], "e_cap_db": computed["e_cap_db"],
            "dt_s": computed["dt_s"], "wall_pred_s": computed["wall_pred_s"],
            "budget_wall_s": computed["budget_wall_s"],
            "formula": "NrTS = max(ceil(1.5×NrTS_pred), 帽停步数, 激励步数)；"
                       "t_full = t_cap_end + (E_cap−(−60))/rate_used（慢者）",
        }, root)
        print(f"[stage2:{template}] NrTS 预声明落盘：nrts={s2['nrts']} "
              f"(pred={s2['nrts_pred']} floor={s2['floor_steps']}) "
              f"budget={s2['budget_wall_s'] and round(s2['budget_wall_s'])}s",
              flush=True)
    if s2.get("converged_in_stage1"):
        return judge_fullcurve_stage1_as_full(template, root)
    result_path = work / "_smoke_result.json"
    cap_path = work / "_stage2_result.json"
    if not result_path.exists() and not cap_path.exists():
        budget = float(s2["budget_wall_s"] or 0.0)
        smoke_timeout = (budget + STAGE2_SMOKE_MARGIN_S if budget > 0
                         else 14.0 * 3600.0)
        runner_timeout = smoke_timeout + STAGE2_RUNNER_MARGIN_S
        work.mkdir(parents=True, exist_ok=True)
        cmd = stage_cmd(template, "stage2", smoke_timeout, nrts=int(s2["nrts"]),
                        root=root)
        foreign = (guard or oe_foreign_running)()
        if foreign:
            return {"template": template, "verdict": "REFUSED",
                    "reasons": [f"#261 互斥：检测到在跑 openEMS 进程：{foreign}"]}
        lock_path = _lock_path(root)
        owner = acquire_lock(f"c3_fullcurve_stage2/{template}", lock_path)
        try:
            cwd = REPO if root is None else Path(root)
            print(f"[stage2:{template}] 发射：{' '.join(cmd)}", flush=True)
            if launch_fn is not None:
                outcome = launch_fn(cmd, work=work, template=template,
                                    timeout_s=runner_timeout, budget_s=budget, cwd=cwd)
            else:
                outcome = _launch_stage2_real(cmd, work, template, runner_timeout,
                                              budget, cwd)
            print(f"[stage2:{template}] 引擎结束："
                  f"{json.dumps(outcome, ensure_ascii=False)}", flush=True)
            if outcome.get("killed"):
                _write_cap_result(template, work, outcome, s2)
        finally:
            release_lock(owner, lock_path)
    return judge_fullcurve(template, root)


def _write_cap_result(template: str, work: Path, outcome: dict[str, Any],
                      s2: dict[str, Any]) -> None:
    """帽停/blocked 快照落档（PARTIAL(超预算) 语义，产物双记不删，#328）。"""
    doc = {"template": template, "stage": "stage2", "criteria": CRITERIA_A,
           "verdict": "FAIL_NOT_CONVERGED",
           "reason": ("blocked：4h 能量 >−10dB，杀树上报"
                      if outcome.get("killed") == "blocked"
                      else "runner 挂死守卫触发（smoke 预算帽自杀未生效）"),
           "killed": outcome.get("killed"),
           "blocked_reason": outcome.get("blocked_reason"),
           "budget": {"budget_wall_s": s2.get("budget_wall_s"), "nrts": s2.get("nrts")},
           "snapshot": {"port_ut_t_end_s": port_ut_tail_seconds(work),
                        "last_energy_db": last_engine_energy(work),
                        "nrts_declared": s2.get("nrts")},
           "generated_utc": utc_now()}
    (work / "_stage2_result.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


# ─── 判读（G0-G4，criteria_a.md §四；judge_refix 口径 + 当轮 PRED_SHIFT）────────

def band_center_3db(f: np.ndarray, s_db: np.ndarray) -> dict:
    """全局峰邻域连续 −3dB 带（含峰的最大连通段）→ 中心/边沿/带宽；另记包络口径。

    （杂项批 2②：原 judge_refix.py:51 只读 import 改
    本脚本内逐位拷贝——判读链脱 runs/ 证据树 import 依赖；判读数字须与归档
    口径逐位一致，本函数体任一侧改动须双侧同步并跑通 test_c3_fullcurve_runner
    的 G1 dev=0 端到端钉背书。）
    """
    i = int(np.argmax(s_db))
    pk = float(s_db[i])
    m = s_db >= pk - 3.0
    lo = i
    while lo > 0 and m[lo - 1]:
        lo -= 1
    hi = i
    while hi < f.size - 1 and m[hi + 1]:
        hi += 1
    fc = 0.5 * (float(f[lo]) + float(f[hi]))
    idx = np.where(m)[0]
    env_lo, env_hi = float(f[idx[0]]), float(f[idx[-1]])
    return {"peak_db": pk, "f_peak_argmax_ghz": float(f[i]),
            "f_lo_ghz": float(f[lo]), "f_hi_ghz": float(f[hi]),
            "f_center_3db_ghz": fc, "bw_3db_pct": (float(f[hi]) - float(f[lo])) / fc * 100.0,
            "touches_sweep_edge": bool(lo == 0 or hi == f.size - 1),
            "envelope_lo_ghz": env_lo, "envelope_hi_ghz": env_hi,
            "envelope_center_ghz": 0.5 * (env_lo + env_hi),
            "n_points_in_band": int(hi - lo + 1)}


def _current_round_pred(template: str, f_ghz: np.ndarray,
                        h_mm: float) -> dict[str, Any]:
    """当轮 PRED_SHIFT（budget_replan mandate：当轮频轴重算写死）：
    pred_shift_new_vs_f0_pct = c3_circuit_sparams(重设计名义, l_via_h=None)
    的 −3dB 带心 / 2.5 − 1（band_center_3db 口径）。"""
    nominal = dict(TEMPLATE_NOMINAL[template])
    circ = c3_circuit_sparams(template, f_ghz, nominal, synchronous_tem=False,
                              h_mm=h_mm, l_via_h=None)
    bc = band_center_3db(f_ghz, 20.0 * np.log10(np.abs(circ[:, 1, 0]) + 1e-12))
    return {"pred_shift_new_vs_f0_pct": (bc["f_center_3db_ghz"] / F0_GHZ - 1.0) * 100.0,
            "circuit_band_center_ghz": bc["f_center_3db_ghz"],
            "circuit_bw_3db_pct": bc["bw_3db_pct"],
            "touches_sweep_edge": bc["touches_sweep_edge"],
            "source": "当轮频轴 c3_circuit_sparams(TEMPLATE_NOMINAL, l_via_h=None) 重算"}


def _load_cpass_pred(cpass_path: Path, template: str) -> float | None:
    try:
        doc = json.loads(cpass_path.read_text(encoding="utf-8"))
        return float(doc["templates"][template]["pred_shift"]["pred_shift_new_vs_f0_pct"])
    except Exception:                                  # 观测性 best-effort（#105）
        return None


def judge_fullcurve(template: str, root: Path | None = None,
                    cpass_path: Path | None = None) -> dict[str, Any]:
    """stage2 全曲线判读 G0-G4 + 预算帽 → _judge_a.json（离线可重放）。"""
    cpass_path = cpass_path or CPASS_PATH
    work = stage_dir(template, "stage2", root)
    out = work / "_judge_a.json"
    res: dict[str, Any] = {}
    res_path = work / "_smoke_result.json"
    cap_path = work / "_stage2_result.json"
    if res_path.exists():
        res = json.loads(res_path.read_text(encoding="utf-8"))
    elif cap_path.exists():
        doc = json.loads(cap_path.read_text(encoding="utf-8"))
        doc["judged_utc"] = utc_now()
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
        print(f"[{template}] verdict={doc['verdict']}（帽停快照，无 sparams 不判 G1-G4）")
        return doc
    else:
        doc = {"template": template, "verdict": "FAIL_NOT_CONVERGED",
               "reason": "stage2 无产物（缺 _smoke_result.json/_stage2_result.json）",
               "snapshot": {"port_ut_t_end_s": port_ut_tail_seconds(work),
                            "last_energy_db": last_engine_energy(work)},
               "judged_utc": utc_now()}
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
        return doc
    csv_path = work / "sparams.csv"
    conv = res.get("convergence") or nrts_convergence(res.get("engine") or {})
    g0 = {"ok": bool(conv["converged"]), "reason": conv["reason"],
          "min_energy_db": conv["min_energy_db"],
          "end_criteria_db": conv["end_criteria_db"],
          "iterations_done": conv["iterations_done"], "nrts": conv["nrts"],
          "hit_nrts_limit": conv["hit_nrts_limit"]}
    if not csv_path.exists():
        doc = {"template": template, "verdict": "FAIL_NOT_CONVERGED",
               "reason": "自然停/帽停但无 sparams.csv（数据不采信，G1-G4 不判）",
               "G0_converged": g0, "engine": res.get("engine"),
               "judged_utc": utc_now()}
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
        return doc
    data = np.loadtxt(csv_path, delimiter=",", skiprows=1)
    f = data[:, 0] / 1e9
    s11 = data[:, 1] + 1j * data[:, 2]
    s21 = data[:, 3] + 1j * data[:, 4]
    s11_db = 20 * np.log10(np.abs(s11) + 1e-12)
    s21_db = 20 * np.log10(np.abs(s21) + 1e-12)
    h_mm = float(Stackup.from_materials_yaml(SUBSTRATE).thickness_mm)

    # G1：当轮 PRED_SHIFT（当轮频轴重算）；cpass 存档值交叉记录
    pred = _current_round_pred(template, f, h_mm)
    pred_stored = _load_cpass_pred(cpass_path, template)
    em = band_center_3db(f, s21_db)
    shift = (em["f_center_3db_ghz"] / F0_GHZ - 1.0) * 100.0
    dev = abs(shift - pred["pred_shift_new_vs_f0_pct"])
    g1_status = ("PASS" if dev <= G1_PASS_PT
                 else "PARTIAL" if dev <= G1_PARTIAL_PT else "FAIL")
    drift = (round(shift - pred_stored, 4) if pred_stored is not None else None)
    g1 = {"status": g1_status, "shift_measured_pct": shift,
          "shift_predicted_pct": pred["pred_shift_new_vs_f0_pct"],
          "abs_dev_pt": dev, "thresholds_pt": [G1_PASS_PT, G1_PARTIAL_PT],
          "pred_source": pred["source"],
          "pred_stored_cpass_pct": pred_stored,
          "pred_drift_pt": drift,
          "pred_drift_note": ("只记录不进门（>0.5pt 提示当轮与 (c) 存档口径漂移）"
                              if drift is not None and abs(drift) > PRED_DRIFT_RECORD_PT
                              else None),
          "em_band": em}

    # G2：通带峰 ≥−3dB 且**设计带内** max|S11| ≤−10dB。
    # 带内口径勘误（预声明留痕）：−3dB 带缘处 |S21|=−3dB ⇒ 无源性恒等式强制
    # |S11|≈−3.01dB，"−3dB 带内 RL≤−10dB" 物理上不可满足（judge_refix 原 G2
    # 未被全曲线数据实证过的潜在缺陷）；判据面取设计带（f0±fbw/2，smoke 五门
    # rl_band_max_db 同口径），−3dB 带内 RL 降级为只记录。
    band = (f >= em["f_lo_ghz"]) & (f <= em["f_hi_ghz"])
    dband = (f >= F0_GHZ * (1 - FBW / 2)) & (f <= F0_GHZ * (1 + FBW / 2))
    peak = float(s21_db.max())
    rl_in = float(s11_db[dband].max())
    ok_peak = peak >= G2_PEAK_MIN_DB
    ok_rl = rl_in <= G2_RL_MAX_DB
    g2_status = ("PASS" if (ok_peak and ok_rl)
                 else "PARTIAL" if (ok_peak or ok_rl) else "FAIL")
    g2 = {"status": g2_status, "peak_s21_db": peak, "peak_ok": ok_peak,
          "rl_design_band_max_db": rl_in, "rl_ok": ok_rl,
          "rl_3db_band_max_db": float(s11_db[band].max()),
          "rl_band_semantics": "判据面=设计带 f0±fbw/2（−3dB 带缘 RL 不可满足，"
                               "见 criteria_a.md §四勘误）；−3dB 带内只记录",
          "thresholds": {"peak_min_db": G2_PEAK_MIN_DB, "rl_max_db": G2_RL_MAX_DB},
          "design_band_s21_max_db": float(s21_db[dband].max()),
          "bw_3db_pct": em["bw_3db_pct"], "design_fbw_pct": FBW * 100,
          "bw_ratio_vs_design": em["bw_3db_pct"] / (FBW * 100)}

    # G3：引擎 ZL 只记录（#280；best-effort #105）
    g3: dict[str, Any] = {"note": "只记录不进门（#280）",
                          "z0_ref_used_in_calcport": 50.0}
    pdir = work / "fdtd"
    if pdir.exists():
        try:
            from rfauto.adapters.openems_rotation import engine_msl_line_z0
            fsel = (f >= F0_GHZ * (1 - G3_BAND_REL)) & (f <= F0_GHZ * (1 + G3_BAND_REL))
            for p in (1, 2):
                try:
                    zl = engine_msl_line_z0(pdir, p, f * 1e9)
                except Exception as exc:
                    g3[f"port{p}_error"] = repr(exc)
                    continue
                if zl is None:
                    g3[f"port{p}_zl_ohm"] = None
                    continue
                zr = float(np.median(np.real(np.asarray(zl)[fsel])))
                g3[f"port{p}_zl_ohm"] = zr
                g3[f"port{p}_dev_pct"] = (zr / 50.0 - 1.0) * 100.0
        except Exception as exc:
            g3["error"] = repr(exc)
    else:
        g3["note"] += "（无 fdtd/ 目录，ZL 不可复算）"

    # G4：无源性（单激励互易 N/A 同 judge_refix）
    power = np.abs(s11) ** 2 + np.abs(s21) ** 2
    power_max = float(power.max())
    g4 = {"status": "N/A", "note": "单激励（port1 excite=1）仅 S11/S21，x 镜像对称 ⇒ "
                                   "S12=S21/S22=S11 由构造保证",
          "passivity_power_sum_max": power_max,
          "passivity_ok": bool(power_max <= POWER_SUM_MAX),
          "threshold": POWER_SUM_MAX}

    # verdict 映射（judge_refix 同款）+ 预算硬帽 1.5×（criteria_a.md §四）
    if not g0["ok"]:
        verdict = "FAIL_NOT_CONVERGED"
    elif g1_status == "FAIL" or g2_status == "FAIL":
        verdict = "FAIL"
    elif g1_status == "PASS" and g2_status == "PASS" and g4["passivity_ok"]:
        verdict = "PASS"
    else:
        verdict = "PARTIAL"
    solve_s = res.get("solve_s") or (res.get("engine") or {}).get("engine_wall_s")
    plan = _plan_load(root)
    s2 = (plan.get("templates", {}).get(template, {}) or {}).get("stage2") or {}
    budget_wall_s = s2.get("budget_wall_s")
    over_budget = bool(budget_wall_s is not None and solve_s is not None
                       and float(solve_s) > float(budget_wall_s))
    if over_budget and verdict == "PASS":
        verdict = "PARTIAL"
    budget = {"budget_wall_s": budget_wall_s, "solve_s": solve_s,
              "over_budget": over_budget,
              "note": ("超 1.5× 预算硬帽 → 至最坏 PARTIAL(超预算)，产物双记不删"
                       if over_budget else None)}

    doc = {"template": template, "verdict": verdict, "criteria": CRITERIA_A,
           "G0_converged": g0, "G1_peak_shift": g1, "G2_il_rl": g2,
           "G3_engine_zl": g3, "G4_reciprocity": g4, "budget": budget,
           "run": {"nrts": res.get("nrts"), "mesh_mm": res.get("mesh_mm"),
                   "solve_s": solve_s, "rc": res.get("rc"),
                   "n_freq": int(f.size), "engine": res.get("engine")},
           "judged_utc": utc_now()}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(f"[{template}] verdict={verdict} | G0 {g0['ok']} ({g0['min_energy_db']}dB) | "
          f"G1 {g1_status}: 带心 {em['f_center_3db_ghz']:.4f}GHz shift {shift:+.3f}% "
          f"vs pred {pred['pred_shift_new_vs_f0_pct']:+.3f}% (dev {dev:.2f}pt) | "
          f"G2 {g2_status}: peak {peak:.2f}dB RL {rl_in:.1f}dB | "
          f"G4 passivity {power_max:.4f} | budget over={over_budget}")
    return doc


def judge_fullcurve_stage1_as_full(template: str,
                                   root: Path | None = None) -> dict[str, Any]:
    """stage1 帽内自然收敛分支：stage1 即全曲线（stage2 跳过）；本分支正常不应
    发生（EndCriteria −60dB 需 ~10h ≫ 1.4h 帽），发生即如实记录。"""
    summary = summarize_stage1(template, root)
    return {"template": template,
            "verdict": ("PASS" if summary["sentinel"]["ok"] else "SENTINEL_FAIL"),
            "note": "stage1 帽内已自然收敛（converged_in_stage1），stage2 跳过；"
                    "全 G1-G4 判读需 sparams.csv，见 stage1 _smoke_result.json",
            "stage1_summary_verdict": summary.get("verdict")}


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--template", choices=sorted(C3_TEMPLATES), default=None)
    ap.add_argument("--stage", choices=("stage1", "stage2"), default=None)
    ap.add_argument("--plan", action="store_true",
                    help="离线：三模板基座落盘（不可变）")
    ap.add_argument("--force-plan", action="store_true",
                    help="覆盖已存在 plan 基座（主代理裁决留痕）")
    ap.add_argument("--judge", action="store_true", help="离线：stage2 全曲线判读")
    ap.add_argument("--stage1-cap-s", type=float, default=STAGE1_TIMEOUT_S,
                    help="stage1 帽秒（防挂死非预算门；缺省 5040=1.4h。数据不足重跑"
                         "可加大——须同步 criteria_a 修订留痕）")
    ap.add_argument("--judge-stage1", action="store_true",
                    help="离线：stage1 帽停部分产物判读（stage1_partial_verdict "
                         "重放盘上产物，不发射引擎）")
    ap.add_argument("--root", default=None,
                    help="产物根（缺省 runs/smoke_c3_fullcurve）")
    ap.add_argument("--nominals", default=None,
                    help="R2 当轮重设计名义 doc（redesign_nominals.json；缺省 "
                         "runs/smoke_c3_redesign 存档，行为不变）")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else None
    nominals_path = Path(args.nominals) if args.nominals else None
    if args.plan:
        build_plan(root, force=args.force_plan, nominals_path=nominals_path)
        return 0
    if not args.template or not (args.stage or args.judge or args.judge_stage1):
        ap.error("须给 --template + (--stage stage1|stage2 | --judge | --judge-stage1)")
    if args.judge_stage1:
        doc = stage1_partial_verdict(args.template, root)
        print(f"[{args.template}] stage1_verdict={doc.get('verdict')} "
              f"basis={doc.get('basis')} fail_kind={doc.get('fail_kind')} "
              f"rates={json.dumps(doc.get('rates'))}", flush=True)
        print(f"[{args.template}] stage2_plan={json.dumps(doc.get('stage2_plan'))}",
              flush=True)
        print(f"STAGE1J_{args.template.upper()}_{doc.get('verdict')}", flush=True)
        return 0 if doc.get("verdict") == "PASS" else 1
    if args.stage == "stage1":
        summary = run_stage1(args.template, root, cap_s=args.stage1_cap_s)
        vdoc = summary.get("stage1_verdict") or {}
        ok = (summary.get("verdict") == "SENTINEL_PASS"
              or vdoc.get("verdict") == "PASS")
        print(f"STAGE1_{args.template.upper()}_{vdoc.get('verdict') or summary.get('verdict')}",
              flush=True)
        return 0 if ok else 1
    if args.stage == "stage2":
        out = run_stage2(args.template, root)
        print(f"STAGE2_{args.template.upper()}_{out.get('verdict')}", flush=True)
        return 0 if out.get("verdict") in ("PASS", "PARTIAL") else 1
    out = judge_fullcurve(args.template, root)
    return 0 if out.get("verdict") in ("PASS", "PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())
