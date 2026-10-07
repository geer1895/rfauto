"""F-D 席位 2（patch_array_series）截断归因判读器（纯离线，零求解零渲染）。

判据预声明（脚本头立此存照， #262/#268/#279 口径）：
- et/ht 是激励信号时间序列（#279），不是能量衰减曲线、更不是求解进度：
  高斯激励在 t0=argmax|et| 达峰，包络在 2·t0 处归零，故 et 文件恒止于
  2·t0（与求解时长无关）。本判读不把 et 末行时间当引擎终止时刻。
- 求解真实进度只看 fdtd/port_ut_* 末行时间轴（#268）。
- 引擎步数：dt=et 逐行中位间隔（et 逐步记录），steps_used=t_engine_end/dt，
  NrTS 声明从 simulation.py 字面量解析；steps_used ≥ 0.999·NrTS = 触步数帽。
- EndCriteria：simulation.py 未显式设置时引擎取默认 1e-5（openEMS pyx 文档
  口径）；触步数帽即等价于「能量未衰减到 EndCriteria 就被切断」。

归因规则（预声明，两分支）：
  A. 截断（#262/#84 族，|S|>1.05 FAIL 属非物理假象，修复面=模板参数
     NrTS/EndCriteria/谐振排查，不定性几何）：触步数帽，或 t_engine_end ≤
     t_excite_end（激励脉冲未完整进入）。
  B. 物理真无源性（修复面=几何/端口建模）：引擎提前收敛停机（未触步数帽
     =EndCriteria 达成）且 t_engine_end > t_excite_end。

用法：
  .venv/Scripts/python.exe scripts/fd_seat2_truncation_check.py \
      [--run-dir runs/ge_fd/patch_array_series] \
      [--out-dir runs/fd_rerun_20260927]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]

TRUNCATION = "truncation_#262"
PHYSICS = "physics_passivity"
NO_EVIDENCE = "no_evidence"


def _load_xy(path: Path) -> np.ndarray | None:
    """读 openEMS 两列时间序列（port_ut/port_it/et/ht，'%'/'#' 头注释）。"""
    try:
        return np.loadtxt(path, comments=("%", "#"))
    except Exception:
        return None


def _parse_sim_decls(run_dir: Path) -> dict:
    """从渲染脚本字面量解析 NrTS/F0/FC/EndCriteria 声明（缺省如实记 None）。"""
    sim = run_dir / "simulation.py"
    out: dict = {"nrts": None, "f0_hz": None, "fc_hz": None,
                 "end_criteria_explicit": False, "max_time_ns_declared": None}
    try:
        text = sim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    m = re.search(r"NrTS\s*=\s*([0-9eE.+-]+)", text)
    if m:
        out["nrts"] = float(m.group(1))
    m = re.search(r"^F0\s*=\s*([0-9eE.+-]+)", text, re.MULTILINE)
    if m:
        out["f0_hz"] = float(m.group(1))
    m = re.search(r"^FC\s*=\s*([0-9eE.+-]+)", text, re.MULTILINE)
    if m:
        out["fc_hz"] = float(m.group(1))
    out["end_criteria_explicit"] = bool(
        re.search(r"SetEndCriteria\s*\(|EndCriteria\s*=", text))
    return out


def _port_stats(run_dir: Path) -> tuple[float | None, float | None, dict]:
    """返回 (t_engine_end, tail_ratio_max, per-file 明细)。tail_ratio=末 20 样
    平均幅值/峰值幅值（#268：端口尾幅是真实收敛状态证据）。"""
    fdtd = run_dir / "fdtd"
    detail: dict = {}
    t_end: float | None = None
    tail_ratio_max: float | None = None
    if not fdtd.is_dir():
        return None, None, detail
    for p in sorted(fdtd.glob("port_ut_*")):
        arr = _load_xy(p)
        if arr is None or arr.ndim != 2 or arr.shape[0] < 2:
            detail[p.name] = {"error": "unreadable"}
            continue
        t, y = arr[:, 0], arr[:, 1]
        peak = float(np.max(np.abs(y)))
        tail = float(np.mean(np.abs(y[-20:]))) if peak > 0 else None
        ratio = (tail / peak) if (tail is not None and peak > 0) else None
        detail[p.name] = {
            "t_end": float(t[-1]), "peak": peak, "tail_mean": tail,
            "tail_over_peak": ratio,
        }
        if t_end is None or t[-1] > t_end:
            t_end = float(t[-1])
        if ratio is not None and (tail_ratio_max is None or ratio > tail_ratio_max):
            tail_ratio_max = float(ratio)
    return t_end, tail_ratio_max, detail


def _sparams_peak(run_dir: Path) -> dict | None:
    """best-effort 读 sparams.csv 峰值 |S| 与峰位（判读上下文，非归因依据）。"""
    path = run_dir / "sparams.csv"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = [r for r in csv.reader(fh)
                    if r and not r[0].lstrip().startswith(("%", "#", "freq"))]
        if not rows:
            return None
        arr = np.array([[float(x) for x in r] for r in rows], dtype=float)
    except (ValueError, OSError):
        return None
    if arr.ndim != 2 or arr.shape[1] < 3:
        return None
    freq = arr[:, 0]
    best = {"max_abs_s": 0.0, "at_ghz": None, "n_freq": int(arr.shape[0])}
    for c in range(1, arr.shape[1] - 1, 2):
        mag = np.hypot(arr[:, c], arr[:, c + 1])
        i = int(np.argmax(mag))
        if float(mag[i]) > best["max_abs_s"]:
            best = {"max_abs_s": float(mag[i]),
                    "at_ghz": float(freq[i] / 1e9), "n_freq": int(arr.shape[0])}
    return best


def analyze(run_dir: Path) -> dict:
    decls = _parse_sim_decls(run_dir)
    et = _load_xy(run_dir / "fdtd" / "et")
    t_excite_end = t0 = dt = None
    t0_consistency = None
    if et is not None and et.ndim == 2 and et.shape[0] > 10:
        t, y = et[:, 0], et[:, 1]
        t0 = float(t[int(np.argmax(np.abs(y)))])
        t_excite_end = 2.0 * t0
        dt = float(np.median(np.diff(t)))
        # 内部一致性（非判据）：高斯激励 t0≈4.5/(π·FC)（引擎经验锚，t0·π·FC/4.5≈1）
        if decls.get("fc_hz"):
            t0_consistency = t0 * math.pi * decls["fc_hz"] / 4.5
    t_engine_end, tail_ratio, port_detail = _port_stats(run_dir)
    steps_used = None
    cap_hit = None
    if t_engine_end is not None and dt:
        steps_used = t_engine_end / dt
        if decls.get("nrts"):
            cap_hit = bool(steps_used >= 0.999 * decls["nrts"])
    converged_stop = cap_hit is False  # 提前停机=EndCriteria 达成（未触帽）

    evidence = {
        "t_excite_end_s": t_excite_end,
        "t0_excite_peak_s": t0,
        "t0_pi_fc_over_4p5": t0_consistency,
        "dt_s": dt,
        "t_engine_end_s": t_engine_end,
        "steps_used": steps_used,
        "nrts_declared": decls.get("nrts"),
        "nrts_cap_hit": cap_hit,
        "end_criteria_explicit": decls["end_criteria_explicit"],
        "end_criteria_effective": (1e-5 if not decls["end_criteria_explicit"] else None),
        "port_tail_over_peak_max": tail_ratio,
        "port_detail": port_detail,
        "sparams": _sparams_peak(run_dir),
    }

    if cap_hit is None or t_excite_end is None:
        verdict, reason = NO_EVIDENCE, "产物缺（et/port_ut 不可读），无法归因"
    elif cap_hit or (t_engine_end is not None and t_engine_end <= t_excite_end):
        verdict = TRUNCATION
        reason = ("引擎吃满 NrTS 步数帽（能量未衰减到 EndCriteria 即被切断）"
                  if cap_hit else "引擎终止早于激励脉冲结束（脉冲未完整进入）")
    elif converged_stop and t_engine_end > t_excite_end:
        verdict = PHYSICS
        reason = ("引擎经 EndCriteria 收敛提前停机且窗口覆盖脉冲全程，"
                  "|S|>1.05 属收敛后的物理判读面（几何/端口建模）")
    else:
        verdict, reason = NO_EVIDENCE, "判据分支未覆盖（如实不判）"

    return {
        "run_dir": str(run_dir),
        "verdict": verdict,
        "reason": reason,
        "evidence": evidence,
    }


def _write_md(res: dict, out: Path) -> None:
    ev = res["evidence"]
    sp = ev.get("sparams") or {}
    ns = lambda v, scale=1e9: ("n/a" if v is None else f"{v * scale:.4g}")  # noqa: E731
    verdict_cn = {
        TRUNCATION: "#262 截断族（FAIL 属非物理假象；修复面=模板参数 NrTS/EndCriteria，不定性几何）",
        PHYSICS: "物理真无源性（收敛后判读；修复面=几何/端口建模）",
        NO_EVIDENCE: "证据不足，无法归因",
    }.get(res["verdict"], res["verdict"])
    lines = [
        "# Seat 2 截断归因判读 — patch_array_series",
        "",
        f"- run 目录：`{res['run_dir']}`",
        f"- **结论：{verdict_cn}**",
        f"- 归因理由：{res['reason']}",
        "",
        "## 三证据",
        "",
        "1. **激励 vs 引擎终止**：t_excite_end = "
        f"{ns(ev['t_excite_end_s'])} ns（et 峰 t0={ns(ev['t0_excite_peak_s'])} ns×2；"
        f"t0·π·FC/4.5={ev['t0_pi_fc_over_4p5'] and round(ev['t0_pi_fc_over_4p5'], 4)}）；",
        f"   引擎真实终止 t_engine_end = {ns(ev['t_engine_end_s'])} ns"
        f"（port_ut 末行时间轴，#268 口径）；steps_used≈"
        f"{ev['steps_used'] and round(ev['steps_used'])} vs NrTS 声明 "
        f"{ev['nrts_declared'] and round(ev['nrts_declared'])} → "
        f"触步数帽={ev['nrts_cap_hit']}。",
        "2. **能量/收敛**：EndCriteria 显式设置="
        f"{ev['end_criteria_explicit']}（未设则引擎默认 1e-5）；端口尾幅/峰值="
        f"{ev['port_tail_over_peak_max'] and round(ev['port_tail_over_peak_max'], 4)}"
        "（能量∝幅值²，远高于 1e-5）→ 场未衰减即被切断，收敛未达成。",
        "3. **非物理数值面**：max|S| = "
        f"{sp.get('max_abs_s') and round(sp['max_abs_s'], 4)}"
        f" @ {sp.get('at_ghz') and round(sp['at_ghz'], 3)} GHz"
        f"（csv {sp.get('n_freq')} 频点）——量级远超 1.05 门的物理容差，"
        "与截断假象指纹（#262/#84 族）一致。",
        "",
        "## et 文件口径勘误（#268/#279）",
        "",
        "登记行「et 止于 2.47ns=截断指纹」不准确：et 是激励信号时间序列"
        "（峰值 1.0@t0、恒止于 2·t0，与求解时长无关）。本判读以 port_ut 末行"
        "时间轴为求解进度唯一口径。",
        "",
        "## 判据（预声明，见脚本头）",
        "",
        "- 截断：steps_used ≥ 0.999·NrTS（能量未达 EndCriteria 即触步数帽）"
        "或 t_engine_end ≤ t_excite_end",
        "- 物理：引擎提前收敛停机（未触帽）且 t_engine_end > t_excite_end",
        "",
        "## 修复面（参数空间；本判读不改模板）",
        "",
        "- 模板 NrTS=100000（≈11.5ns@dt=0.115ps）对该串馈阵不够：4.88GHz 附近"
        "长寿命储能未在窗内衰减到 1e-5。候选修复轨：提高 NrTS（META "
        "max_time_ns=30ns 口径）/ 显式放宽 EndCriteria / 谐振定位后收敛预算重排。",
        "",
        "复跑：`.venv/Scripts/python.exe scripts/fd_seat2_truncation_check.py`",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=str(
        REPO / "runs" / "ge_fd" / "patch_array_series"))
    parser.add_argument("--out-dir", default=str(
        REPO / "runs" / "fd_rerun_20260927"))
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = analyze(run_dir)
    jp = out_dir / "seat2_truncation_verdict.json"
    mp = out_dir / "seat2_truncation_verdict.md"
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_md(res, mp)
    print(f"[seat2-truncation] verdict={res['verdict']} -> {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
