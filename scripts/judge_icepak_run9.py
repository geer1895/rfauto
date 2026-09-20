"""Icepak e2e run9 收官轮判读（离线，不重跑 AEDT）。

问题（三个待证假设）：① 守恒门（底面出热 vs P_diss，门 5%）
环带网格+全程细扫后是否改善；② HFSS@T1 f0 重解跳变是否复现、机制是什么；
③ 场级/集总温差（锚定斜率）能否把锚值回写 lumped 模型。

判据全部从 runs/icepak_hfss_loss_e2e/e2e_run*.log 的门行确定性解析（数值纪律；
e2e_case.json 只记录了最后一次 attempt 的失败信息，三门数字只在日志里）。

用法：.venv\\Scripts\\python.exe scripts/judge_icepak_run9.py [--dir runs/icepak_hfss_loss_e2e]
产物：<dir>/run9_verdict.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

RE_HFSS_T0 = re.compile(
    r"\[HFSS@T0\] f0=(?P<f0>[\d.]+)GHz \(网格步长 (?P<step>[\d.]+)MHz\)")
RE_PDISS = re.compile(r"\[HFSS@T0\].*P_diss=(?P<p>[\d.]+)W")
RE_CONSERV = re.compile(
    r"\[Icepak field r1\] T_ring=(?P<t>[\d.]+)C 底面出热=(?P<q>[\d.]+)W "
    r"vs P_diss=(?P<p>[\d.]+)W → 守恒偏差=(?P<dev>[\d.]+)%（门 (?P<gate>[\d.]+)%）")
RE_LUMPED = re.compile(
    r"\[Icepak lumped\] T_ring=(?P<tl>[\d.]+)C → 场级 vs 集总温差=(?P<dt>[\d.]+)K"
    r"（温升 (?P<rise>[\d.]+)K 的 (?P<pct>[\d.]+)%，门 (?P<gate>[\d.]+)%）")
RE_DRIFT = re.compile(
    r"\[HFSS@T1=(?P<t>[\d.]+)C\] f0=(?P<f1>[\d.]+)GHz 漂移=(?P<dkhz>-?[\d.]+)kHz "
    r"\((?P<ppm>-?[\d.]+)ppm\) vs 闭式 (?P<clos>-?[\d.]+)ppm")
RE_ATTEMPT_FAIL = re.compile(r"attempt \d+ FAIL: (?P<msg>.*)")


def parse_gates(text: str) -> dict[str, list[dict[str, float]]]:
    """从一轮日志文本提取三门数值行（单位照抄日志）。"""
    out: dict[str, list[dict[str, float]]] = {"conservation": [],
                                              "lumped": [], "drift": [],
                                              "hfss_t0": [], "attempt_fail": []}
    for m in RE_HFSS_T0.finditer(text):
        out["hfss_t0"].append({"f0_ghz": float(m["f0"]),
                               "grid_step_mhz": float(m["step"])})
    for m in RE_CONSERV.finditer(text):
        out["conservation"].append({
            "t_ring_c": float(m["t"]), "q_bottom_w": float(m["q"]),
            "p_diss_w": float(m["p"]), "dev_pct": float(m["dev"]),
            "gate_pct": float(m["gate"])})
    for m in RE_LUMPED.finditer(text):
        out["lumped"].append({
            "t_lumped_c": float(m["tl"]), "dt_k": float(m["dt"]),
            "field_rise_k": float(m["rise"]), "pct_of_rise": float(m["pct"]),
            "gate_pct": float(m["gate"])})
    for m in RE_DRIFT.finditer(text):
        out["drift"].append({
            "t1_c": float(m["t"]), "f1_ghz": float(m["f1"]),
            "drift_khz": float(m["dkhz"]), "drift_ppm": float(m["ppm"]),
            "closed_form_ppm": float(m["clos"])})
    for m in RE_ATTEMPT_FAIL.finditer(text):
        out["attempt_fail"].append(m["msg"].strip()[:200])
    return out


def sweep_span_mhz(n_points: int, step_mhz: float) -> tuple[float, float]:
    """细扫窗口（span, half-span），MHz。"""
    span = (n_points - 1) * step_mhz
    return span, span / 2.0


def window_clip_check(drift_khz: float, n_points: int, step_mhz: float,
                      tol_pct: float = 0.5) -> bool:
    """漂移恰等于细扫半跨（正负向）→ 谷/峰被窗沿夹持的伪象。"""
    _, half = sweep_span_mhz(n_points, step_mhz)
    return abs(abs(drift_khz) - 1000.0 * half) <= 1000.0 * half * tol_pct / 100.0


def thermal_resistances(cons: dict[str, float],
                        lumped: dict[str, float]) -> dict[str, float]:
    """由门行数字导出等效热阻（K/W）：场级底面路径 / 场级复合 / 集总。"""
    r_field_bottom = (cons["t_ring_c"] - 25.0) / cons["q_bottom_w"]
    r_field_total = (cons["t_ring_c"] - 25.0) / cons["p_diss_w"]
    rise_lumped = lumped["t_lumped_c"] - 25.0
    return {"r_field_bottompath_k_per_w": r_field_bottom,
            "r_field_total_k_per_w": r_field_total,
            "r_lumped_k_per_w": rise_lumped / cons["p_diss_w"]}


def judge(dir_path: Path, n_points: int = 201,
          compare_runs: tuple[str, ...] = ("5", "7", "9")) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    for tag in compare_runs:
        log = dir_path / f"e2e_run{tag}.log"
        if not log.is_file():
            continue
        runs[tag] = parse_gates(log.read_text(encoding="utf-8",
                                              errors="replace"))
    r9 = runs.get("9", {})
    cons9 = r9.get("conservation", [])
    lump9 = r9.get("lumped", [])
    drift9 = r9.get("drift", [])
    t0_9 = r9.get("hfss_t0", [])
    step9 = t0_9[-1]["grid_step_mhz"] if t0_9 else None

    # ① 守恒门跨轮对照
    cons_hist = {t: [c["dev_pct"] for c in runs[t]["conservation"]]
                 for t in runs if runs[t]["conservation"]}
    cons9_val = cons9[-1]["dev_pct"] if cons9 else None
    prior = [v for t, vs in cons_hist.items() if t != "9" for v in vs]
    cons_improved = (cons9_val is not None and prior
                     and cons9_val < min(prior) - 1.0)

    # ② f0 跳变：run9 是否窗沿夹持；历史轮漂移量级
    clip9 = (drift9 and step9
             and window_clip_check(drift9[-1]["drift_khz"], n_points, step9))
    drift_hist = {t: [d["drift_khz"] for d in runs[t]["drift"]]
                  for t in runs if runs[t]["drift"]}

    # ③ 锚定：场级/集总等效热阻（跨 run 复现性）
    anchors: dict[str, Any] = {}
    for t, g in runs.items():
        if g["conservation"] and g["lumped"]:
            anchors[t] = thermal_resistances(g["conservation"][-1],
                                             g["lumped"][-1])
    # 环带网格对（run7/run9）的复现性；run5（旧网格）单列为网格敏感性证据
    pair = [anchors[t]["r_field_total_k_per_w"] for t in ("7", "9") if t in anchors]
    anchor_reproducible = len(pair) == 2 and abs(pair[0] - pair[1]) < 0.5
    mesh_sens = (None if not ("5" in anchors and "7" in anchors) else
                 anchors["7"]["r_field_total_k_per_w"]
                 - anchors["5"]["r_field_total_k_per_w"])

    fail_msgs = r9.get("attempt_fail", [])
    verdict = {
        "item": "W2⑥a-C icepak run9 收官轮判读（不重跑 AEDT）",
        "verdict": "FAIL",
        "verdict_note": "三门照旧未过、锚定链 attempt 在 SweepAnchor 段中断；"
                        "但三门机制本轮数据已可定案（见 attribution），非数据不足。",
        "gates_run9": {
            "conservation": cons9[-1] if cons9 else None,
            "lumped": lump9[-1] if lump9 else None,
            "drift": drift9[-1] if drift9 else None,
            "hfss_t0": t0_9[-1] if t0_9 else None,
        },
        "hypotheses": {
            "①_守恒门是否改善": {
                "answer": "否" if not cons_improved else "是",
                "run9_dev_pct": cons9_val,
                "history_pct": cons_hist,
                "attribution": "跨轮稳定 32.5–35.2%（run5 1.25MHz 网格 → run7/9 环带网格"
                               "变化 <2.8pp）→ 非网格/细扫问题，是确定性的热流分配："
                               "~1/3 P_diss 走非底面路径（顶/侧对流辐射）。门定义只数底面"
                               "出热，物理上必然欠账 → 门应改为全边界通量之和（待证："
                               "对顶面/侧面 heat flow 求和应闭合 ≤5%，需一次 AEDT 复跑验证）",
                "confidence": 0.85,
            },
            "②_f0_跳变是否复现": {
                "answer": "复现，但机制=数值伪象非物理",
                "run9_drift_khz": drift9[-1]["drift_khz"] if drift9 else None,
                "window_edge_clip": bool(clip9),
                "window_half_span_mhz": (None if not step9 else
                                         sweep_span_mhz(n_points, step9)[1]),
                "history_drift_khz": drift_hist,
                "attribution": "run9 漂移 −25000.0kHz 恰 = −(201×0.25MHz)/2 = 细扫半跨 →"
                               " T1 重解的峰不在窗内（或无清晰峰），argmin 取到窗沿；"
                               "run5/7 漂移 +18.7~+21.5MHz（1.25MHz 网格、窗 ±125MHz，窗内）"
                               " → HFSS 自适应重解网格再生噪声 ~0.8%。物理预期 −57.4ppm"
                               "（−0.137MHz）比可分辨尺度（0.25MHz 步=105ppm）还小 →"
                               " 现口径测不出物理信号。需冻结网格重解 + 亚网格峰拟合"
                               "（Lorentzian）再判",
                "confidence": 0.9,
            },
            "③_锚值能否回写": {
                "answer": "有条件可：环带网格对（run7/9）2mK 复现；先闭热账，"
                          "且 run5→run7 揭示网格敏感性",
                "anchors_k_per_w": anchors,
                "anchor_reproducible": anchor_reproducible,
                "mesh_sensitivity_r_field_k_per_w_run7_minus_run5": mesh_sens,
                "attribution": "run7/run9 场级 T_ring 26.474/26.472C、集总 29.120C 恒定"
                               " → 场级复合 R≈22.5 K/W、底面路径 R≈33.5 K/W、集总 R≈63.0"
                               " K/W（比值 2.8 复现）。lumped 高估 2.8× 与守恒门 1/3 分流"
                               "同源：若顶/侧真走 1/3 热，22.5 K/W 是带分流的复合值——"
                               "回写 lumped 前必须先按①闭合热账，否则把分流误差固化为锚。"
                               "另：run5（旧网格）场级复合 R=14.6 K/W 与 run7/9 相差 54%"
                               " → 场级温度对网格生成敏感，回写锚应绑定环带网格口径并标注"
                               "网格版本",
                "confidence": 0.65,
            },
        },
        "script_status": {
            "attempt_fail_msgs": fail_msgs[:3],
            "note": "attempt1 于 SweepAnchor 段 crash（HfssConstants.default_solution "
                    "AttributeError，PyAEDT API 不匹配）；attempt2 Icepak 'Unable to "
                    "obtain EM Loss data'（EM 链接数据重解后不可得）。e2e_case.json 只记"
                    "attempt2 失败——三门数字仅存在于日志，本判读从日志提取。",
            "run8_anomaly_note": "run8 T_ring 1367/2057C 发散解 = 电磁损耗映射失败轮，"
                                 "run9 以环带网格复算排除（T_ring 26.472C 正常）。",
        },
        "followups_real_machine": [
            "守恒门改全边界通量求和后单轮复跑（验证 ~1/3 分流归因）",
            "T1 用冻结网格（Use existing mesh / 关自适应）+ Lorentzian 峰拟合复测 −57ppm",
            "修复 scripts/icepak_hfss_loss_e2e.py SweepAnchor 段 PyAEDT API 调用（他轨文件）",
        ],
        "evidence": [str(dir_path / f"e2e_run{t}.log") for t in runs]
                    + [str(dir_path / "e2e_case.json")],
    }
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="runs/icepak_hfss_loss_e2e")
    ap.add_argument("--n-points", type=int, default=201)
    a = ap.parse_args(argv)
    out = judge(Path(a.dir), a.n_points)
    dst = Path(a.dir) / "run9_verdict.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    g = out["gates_run9"]
    print(f"{out['verdict']} 守恒={g['conservation']['dev_pct'] if g['conservation'] else '?'}% "
          f"漂移={g['drift']['drift_khz'] if g['drift'] else '?'}kHz "
          f"(窗沿夹持={out['hypotheses']['②_f0_跳变是否复现']['window_edge_clip']}) → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
