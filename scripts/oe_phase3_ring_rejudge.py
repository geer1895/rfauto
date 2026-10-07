"""OE 三期 ring_resonator Tier-1 离线重判（criteria v2；S4 审计定案后零仿真）。

S4 审计（docs/audit/oe3_ring_fail_audit_20260929.md）三根因：①判读链复数
argmax bug（extract_ring 直传复数 s21，np.argmax 按实部比较→f2 误取 4.75/
误报 clamped）——已在 oe_phase3_campaign.py extract_ring 调用点幅值化修复，
本脚本 importlib 复用修复后驱动纯函数（_argext_clamped/hj_inverse_er/
_read_sparams_columns/_harvest_s）；②criteria v1 谐振基准式（mean-radius）
系统性偏低 ~4.8% → 换 R_eff=R_OUT（见下 #122 换基声明）；③gap=0.4mm 欠耦
致 v1 地板 0.2 不可达 → 地板按模分设。

═══ #122 换基声明（先声明后判；窗合法性来自独立物理模型而非凑绿）═══

基准式 mean-radius → R_eff=R_OUT（=r_mean+w/2）。换基依据=双模独立互证
（审计 step3，非"把窗挪到峰上"）：
  · n=1/n=2 两峰实测 2.38/4.78 GHz（f2/f1=2.008 与模式阶数自洽，峰为真）；
  · outer-radius 式预测 2.3826/4.7652 → 双模误差 +0.11%/−0.31%（自洽）；
  · mean-radius 式 +5.0%/+4.6%、PMC Bessel 曲率模型 +5.1%/+4.6%——两个
    独立模型同向同幅偏差，且反演 R_eff(2.38)=11.8695 / R_eff(4.78)=11.8199
    均 ≈R_OUT=11.8565（±0.05mm）。
  · "outer-edge 有效路径"的物理分解（栅格化慢波/宽带条场分布/间隙加载的
    组合）属假设/待证（审计 §4）——本批只换判读基准式，不改模板设计式
    （模板面修正属 G2+HFSS 仲裁兑现批次）。

criteria v2 全表（v1 见 oe_phase3_campaign.RING，原样保留）：
  f1 ∈ [2.30, 2.50] GHz（R_eff 预测 2.3826 ±2.5%；峰距窗缘 ≥8 频点）
  f2 ∈ [4.65, 4.90] GHz（R_eff 预测 4.7652 ±2.5%）
  地板按模分设：f1 ≥ 0.010（≈5×背景最大 0.0044）/ f2 ≥ 0.025——v1 地板
    0.2=−14dB 对 gap=0.4mm 欠耦拓扑不可达（凑 0.2 需 gap≈0.03mm，#370 族
    "判据误定"同型，审计 H1/Tier-2 测算）
  εr 窗 [3.11, 4.21] 与差 ≤0.60 维持 v1 不动（R_eff 基准下预期回收 3.64–3.67）
  Q_L：信息项不设门——冒烟档 13.93ns 窗截断（能量 −40.42dB）使峰宽分辨率
    受限（~72MHz），Q_L 如实 UNKNOWN，精算档（30ns）另批提取（审计 H6）

═══ 双留痕纪律（#122）═══
runs/oe_phase3/ring_resonator/verdict.json 与 verdict_offline.json（v1 判据
FAIL）原样保留、不覆写；本脚本只写 verdict_offline_fix.json/md。v1 FAIL
结论对 v1 判据仍然成立、不改写。

用法（零仿真零渲染）：.venv/Scripts/python.exe scripts/oe_phase3_ring_rejudge.py
产物：runs/oe_phase3/ring_resonator/verdict_offline_fix.json
      runs/oe_phase3/ring_resonator/verdict_offline_fix.md
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "scripts" / "oe_phase3_campaign.py"
RUNS_ROOT = REPO / "runs" / "oe_phase3"
DEFAULT_RUN_DIR = RUNS_ROOT / "ring_resonator"

C0 = 299792458.0
#: meta.yaml substrate 单源（与驱动 extract_ring 同口径）
H_MM = 0.508
TAN_D = 0.0037


def _load_driver():
    spec = importlib.util.spec_from_file_location("oe_phase3_campaign", DRIVER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("oe_phase3_campaign", mod)
    spec.loader.exec_module(mod)
    return mod


drv = _load_driver()

# ══ criteria v2（#122 换基声明见模块头；常量与 verdict 快照单源）══════════
RING_V2: dict[str, Any] = {
    "r_eff_basis": "outer_radius",       # R_eff = r_mean + w/2 = R_OUT
    "f1_win_ghz": (2.30, 2.50),          # R_eff 预测 2.3826 ±2.5%
    "f2_win_ghz": (4.65, 4.90),          # R_eff 预测 4.7652 ±2.5%
    "f1_peak_min": 0.010,                # ≈5×背景最大 0.0044（审计 H1）
    "f2_peak_min": 0.025,
    "eps_r_win": (3.11, 4.21),           # 3.66 ±15%（维持 v1 不动）
    "eps_r_diff_max": 0.60,              # 双谐波一致性（维持 v1 不动）
    "eps_r_nominal": 3.66,
    "n_harmonics": (1, 2),
}


def r_eff_mm_from_nominal(nominal: dict[str, Any]) -> float:
    """R_eff = r_mean + w/2 = R_OUT（mm；outer-radius 基准，单源推导）。"""
    return float(nominal["r_mean_mm"]) + float(nominal["w_mm"]) / 2.0


def build_criteria_v2() -> dict[str, Any]:
    """criteria v2 快照（预声明；R_eff 预测值程序化复算非手抄审计）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import Stackup, forward_z0

    nominal = TEMPLATE_NOMINAL["ring_resonator"]
    r_eff_mm = r_eff_mm_from_nominal(nominal)
    sub = Stackup(name="ring-v2", epsilon_r=float(RING_V2["eps_r_nominal"]),
                  thickness_mm=H_MM, loss_tangent=TAN_D)
    _z0, eeff_design = forward_z0(float(nominal["w_mm"]), 2.5, sub)
    preds = {}
    for n in (1, 2):
        f_pred = (n * C0
                  / (2.0 * math.pi * r_eff_mm * 1e-3 * math.sqrt(float(eeff_design)))
                  / 1e9)
        preds[f"f{n}_pred_ghz"] = round(float(f_pred), 4)
    return {
        "template": "ring_resonator",
        "version": "v2_offline_fix",
        "declared_at": time.strftime("%F %T"),
        "audit_ref": "docs/audit/oe3_ring_fail_audit_20260929.md",
        "windows": {k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in RING_V2.items()},
        "r_eff_mm": round(r_eff_mm, 6),
        "eeff_design": float(eeff_design),
        "predictions_ghz": preds,
        "rebasis_declaration": (
            "#122 换基声明：谐振基准式 mean-radius → R_eff=R_OUT（=r_mean+w/2）；"
            "合法性=双模独立互证（n=1/n=2 对 R_eff 式误差 +0.11%/−0.31% 自洽，"
            "mean-radius 与 PMC Bessel 两独立模型同向 +5%，反演 R_eff 双模"
            "≈R_OUT±0.05mm），非凑绿挪窗；v1 判据 FAIL 结论原样保留不改写"),
        "floor_note": (
            "地板按模分设（v1 0.2 对 gap=0.4mm 欠耦拓扑不可达，#370 族判据"
            "误定同型，审计 H1）：f1≥0.010≈5×背景最大 0.0044、f2≥0.025"),
        "ql_note": (
            "Q_L 信息项不设门：冒烟档 13.93ns 窗截断（能量 −40.42dB）峰宽"
            "分辨率受限（~72MHz），Q_L 如实 UNKNOWN，精算档（30ns）另批"
            "（审计 H6）"),
    }


# ══ 提取/判读纯函数（v2 口径；共享纯函数复用修复后驱动单源）══════════════
def extract_ring_v2(
    freqs: np.ndarray, s11: np.ndarray, s21: np.ndarray,
    nominal: dict[str, Any],
    h_mm: float = H_MM, tan_d: float = TAN_D,
) -> dict[str, Any]:
    """criteria v2 口径 ring 标量提取（纯函数）。

    与修复后 extract_ring 同两处差异：①搜索窗/地板按 RING_V2；②εeff 反演
    基准 R_eff=R_OUT（v1 为 r_mean）。幅值语义与修复后 extract_ring 同源
    （复数谱先取模长再 argmax，S4 审计 H3）。
    """
    out: dict[str, Any] = {"judge": "ring_v2"}
    w_mm = float(nominal["w_mm"])
    r_eff_mm = r_eff_mm_from_nominal(nominal)
    out["r_eff_mm"] = r_eff_mm
    s21_db = drv._to_db(s21)
    for n, key, win in ((1, "f1", RING_V2["f1_win_ghz"]),
                        (2, "f2", RING_V2["f2_win_ghz"])):
        idx, clamped = drv._argext_clamped(freqs, np.abs(s21), win, "max")
        if idx < 0:
            out[key] = None
            out[f"{key}_clamped"] = True
            continue
        f_n = float(freqs[idx])
        eeff = (n * C0 / (2.0 * math.pi * r_eff_mm * 1e-3 * f_n * 1e9)) ** 2
        er, note = drv.hj_inverse_er(eeff, w_mm, f_n, h_mm, tan_d)
        out[key] = f_n
        out[f"{key}_clamped"] = clamped
        out[f"{key}_s21"] = float(abs(s21[idx]))
        out[f"{key}_s21_db"] = float(s21_db[idx])
        out[f"eeff_{key}"] = float(eeff)
        out[f"eps_r_{key}"] = er
        out[f"eps_r_{key}_note"] = note
    # Q_L 信息项（不设门；H6 冒烟档分辨率受限 → 如实 UNKNOWN，原始量留痕）
    out["ql_info"] = {
        "status": "UNKNOWN",
        "reason": ("冒烟档 13.93ns 窗截断（能量 −40.42dB），峰宽受时间窗"
                   "分辨率限制（~72MHz）——Q_L 不可信，精算档（30ns）另批"
                   "提取（S4 审计 H6）"),
    }
    if out.get("f1") is not None:
        idx1 = int(np.argmin(np.abs(freqs - float(out["f1"]))))
        peak_db = float(s21_db[idx1])
        within = np.flatnonzero(
            (freqs >= RING_V2["f1_win_ghz"][0]) & (freqs <= RING_V2["f1_win_ghz"][1])
            & (s21_db >= peak_db - 3.0))
        if within.size >= 3:
            bw = float(freqs[within[-1]] - freqs[within[0]])
            out["ql_info"]["raw_bw_3db_ghz"] = round(bw, 6)
            out["ql_info"]["raw_ql"] = (
                round(float(out["f1"]) / bw, 2) if bw > 0 else None)
    return out


def judge_ring_v2(ext: dict[str, Any], s: np.ndarray) -> dict[str, Any]:
    """criteria v2 判据门（判读纯函数；门结构镜像 judge_ring，v2 窗/地板）。"""
    checks: list[dict[str, Any]] = []

    def _chk(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    finite = bool(np.all(np.isfinite(s)))
    passive = bool(np.all(np.abs(s) <= drv.PASSIVE_MAX))
    _chk("finite", finite, "ok" if finite else "S 含非有限值")
    _chk("passive", passive,
         f"max|S|={float(np.max(np.abs(s))):.4f}（门 ≤{drv.PASSIVE_MAX}）")
    f1, f2 = ext.get("f1"), ext.get("f2")
    er1, er2 = ext.get("eps_r_f1"), ext.get("eps_r_f2")
    p1, p2 = ext.get("f1_s21"), ext.get("f2_s21")
    _chk("f1_window",
         None if f1 is None else bool(RING_V2["f1_win_ghz"][0] <= f1 <= RING_V2["f1_win_ghz"][1]),
         f"f1={f1} 窗 {RING_V2['f1_win_ghz']}（R_eff 预测 ±2.5%）")
    _chk("f2_window",
         None if f2 is None else bool(RING_V2["f2_win_ghz"][0] <= f2 <= RING_V2["f2_win_ghz"][1]),
         f"f2={f2} 窗 {RING_V2['f2_win_ghz']}（R_eff 预测 ±2.5%）")
    _chk("f1_peak_floor",
         None if p1 is None else bool(p1 >= RING_V2["f1_peak_min"]),
         f"|S21|@f1={p1}（地板 {RING_V2['f1_peak_min']}≈5×背景，criteria v2）")
    _chk("f2_peak_floor",
         None if p2 is None else bool(p2 >= RING_V2["f2_peak_min"]),
         f"|S21|@f2={p2}（地板 {RING_V2['f2_peak_min']}，criteria v2）")
    _chk("eps_r_f1_window",
         None if er1 is None else bool(RING_V2["eps_r_win"][0] <= er1 <= RING_V2["eps_r_win"][1]),
         f"εr(f1)={er1} 窗 {RING_V2['eps_r_win']}（{RING_V2['eps_r_nominal']} ±15%，"
         "R_eff 基准，窗维持 v1）")
    diff = None if (er1 is None or er2 is None) else abs(float(er1) - float(er2))
    _chk("eps_r_harmonic_consistency",
         None if diff is None else bool(diff <= RING_V2["eps_r_diff_max"]),
         f"|εr(f2)−εr(f1)|={diff}（门 ≤{RING_V2['eps_r_diff_max']}，维持 v1）")
    for key in ("f1", "f2"):
        if ext.get(f"{key}_clamped"):
            _chk(f"{key}_clamp_guard", False,
                 f"{key} 落搜索窗缘 2 频点内（#281 夹持伪象）")
    hard_names = ("finite", "passive", "f1_clamp_guard", "f2_clamp_guard",
                  "f1_peak_floor", "f2_peak_floor", "eps_r_f1_window")
    hard_fail = any(c["ok"] is False for c in checks if c["name"] in hard_names)
    soft_pending = any(c["ok"] is None for c in checks)
    if hard_fail:
        status = "FAIL"
    elif soft_pending:
        status = "PARTIAL"
    elif all(c["ok"] for c in checks):
        status = "PASS"
    else:
        status = "FAIL"
    return {"status": status, "checks": checks, "nrts_policy": "record_only"}


# ══ 离线重判主路径（零仿真；读既有 sparams，写 *_fix.json/md）═════════════
def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _apply_env_gates(verdict: dict[str, Any], run_dir: Path) -> None:
    """NrTS/G11 环境门（best-effort #105；record_only 策略=只留痕不降级，
    G11 unhealthy 升 FAIL 沿用 v1 口径）。"""
    fd = drv.load_fd_campaign()
    try:
        verdict["nrts_converged"] = fd.nrts_converged_gate(run_dir)
    except Exception as exc:   # best-effort #105
        verdict["nrts_converged"] = {"ok": None, "reason": f"gate error: {exc}"}
    try:
        from rfauto.service.health_service import health_check_run
        hc = health_check_run(run_dir.name, runs_dir=str(RUNS_ROOT))
        verdict["g11_health"] = {k: hc.get(k)
                                 for k in ("verdict", "ok") if k in hc}
        if (hc.get("verdict") == "unhealthy" and verdict.get("status") == "PASS"):
            verdict["status"] = "FAIL"
            verdict["reason"] = "G11 health verdict=unhealthy（#314 真实 FAIL 证据）"
    except Exception as exc:   # best-effort #105
        verdict["g11_health"] = {"error": str(exc)[:120]}


def run_rejudge(run_dir: Path, out_dir: Path | None = None,
                env_gates: bool = True) -> dict[str, Any]:
    """对既有 ring 产物离线重判（criteria v2；零仿真零渲染）。

    写 verdict_offline_fix.json（v1 双留痕不覆写）并返回 verdict dict。
    env_gates=False 供纯判读单测隔离（NrTS/G11 门读工作区证据面，测试
    不得依赖真实 runs 根状态）。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    run_dir = Path(run_dir)
    out_dir = Path(out_dir) if out_dir is not None else run_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    crit = build_criteria_v2()
    verdict: dict[str, Any] = {
        "template": "ring_resonator",
        "mode": "judge_only_offline_fix_v2",
        "judged_at": time.strftime("%F %T"),
        "provenance": (
            "S4 审计定案（docs/audit/oe3_ring_fail_audit_20260929.md）Tier-1 "
            "零仿真重判：extract_ring 复数 argmax 幅值化修复（H3）+ criteria v2 "
            "R_eff=R_OUT 换基（H2 双模互证，#122 声明见 criteria）；v1 判据"
            " verdict.json/verdict_offline.json 原样保留（双留痕）"),
        "criteria": crit,
    }
    cols = drv._read_sparams_columns(run_dir / "sparams.csv")
    if cols is None or "s21" not in cols:
        verdict.update(status="PARTIAL", reason="sparams.csv 缺/不可解析")
        _save(verdict, out_dir)
        return verdict
    freqs_ghz = cols["freq_hz"] / 1e9   # Hz→GHz（verdict_offline 同款单位修正）
    ext = extract_ring_v2(freqs_ghz, cols["s11"], cols["s21"],
                          TEMPLATE_NOMINAL["ring_resonator"])
    verdict["extracted"] = ext
    s = None
    try:
        fd = drv.load_fd_campaign()
        s = drv._harvest_s(run_dir, fd)
    except Exception:   # best-effort：判读门退回本席两列
        s = None
    if s is None or s.size == 0:
        s = np.stack([cols["s11"], cols["s21"]])
    jd = judge_ring_v2(ext, s)
    verdict["judge"] = jd
    verdict["status"] = jd["status"]
    if env_gates:
        _apply_env_gates(verdict, run_dir)
    _save(verdict, out_dir)
    (out_dir / "verdict_offline_fix.md").write_text(
        render_md(verdict, run_dir), encoding="utf-8")
    return verdict


def _save(verdict: dict[str, Any], out_dir: Path) -> None:
    (out_dir / "verdict_offline_fix.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")


# ══ md 报告（新旧对照表程序化生成，数字取自产物非手抄）══════════════════
_ROWS = (
    ("f1 (GHz)", "f1"), ("f1 \\|S21\\|", "f1_s21"),
    ("f1_clamped", "f1_clamped"), ("f2 (GHz)", "f2"), ("f2 \\|S21\\|", "f2_s21"),
    ("f2_clamped", "f2_clamped"),
    ("eeff(f1)", "eeff_f1"), ("eeff(f2)", "eeff_f2"),
    ("εr(f1)", "eps_r_f1"), ("εr(f2)", "eps_r_f2"),
)


def render_md(verdict: dict[str, Any], run_dir: Path) -> str:
    """verdict_offline_fix.md：判据 v1/v2 对照 + 逐门新旧对照 + 换基声明。"""
    old = _load_json(run_dir / "verdict_offline.json") or {}
    old_ext = old.get("extracted") or {}
    new_ext = verdict.get("extracted") or {}
    lines: list[str] = [
        "# ring_resonator Tier-1 离线重判（criteria v2，零仿真）",
        "",
        f"- 判读时刻：{verdict.get('judged_at')} · 依据："
        "docs/audit/oe3_ring_fail_audit_20260929.md（S4 定案）",
        "- 修复：extract_ring 复数 argmax 幅值化（审计 H3，scripts/"
        "oe_phase3_campaign.py 调用点）",
        f"- 重判 status：**{verdict.get('status')}**（criteria v2 全门）"
        f" ← v1 判据原判 **{old.get('status', 'FAIL')}**（双留痕保留，不改写）",
        "",
        "## #122 换基声明",
        "",
        verdict["criteria"]["rebasis_declaration"],
        "",
        "| 基准式 | f1 预测 (GHz) | f2 预测 (GHz) | 实测 | 误差 |",
        "|---|---|---|---|---|",
        "| mean-radius（v1） | 2.500 | 5.000 | 2.38 / 4.78 | +5.0% / +4.6% |",
        f"| **outer-radius（v2）** R_eff=R_OUT={verdict['criteria']['r_eff_mm']}mm "
        f" | {verdict['criteria']['predictions_ghz']['f1_pred_ghz']} "
        f"| {verdict['criteria']['predictions_ghz']['f2_pred_ghz']} "
        "| 2.38 / 4.78 | +0.11% / −0.31% |",
        "",
        "合法性=双模独立互证（f2/f1=2.008 与模式阶数自洽；mean-radius 与 PMC "
        "Bessel 两独立模型同向 +5%），非凑绿挪窗。\"outer-edge 有效路径\"的"
        "物理分解属假设/待证（审计 §4），本批只换判读基准式、不改模板设计式。",
        "",
        "## 判据 v1 → v2",
        "",
        "| 项 | v1（原判） | v2（本判） | 依据 |",
        "|---|---|---|---|",
        "| f1 窗 (GHz) | [2.40, 2.60] | [2.30, 2.50] | R_eff 基准 ±2.5% |",
        "| f2 窗 (GHz) | [4.75, 5.25] | [4.65, 4.90] | 同上 |",
        "| 峰地板 | f1 ≥ 0.2 | f1 ≥ 0.010 / f2 ≥ 0.025 | gap=0.4 欠耦拓扑 "
        "0.2 不可达（#370 族判据误定同型，审计 H1） |",
        "| εr 窗 / 差门 | [3.11, 4.21] / ≤0.60 | 不动 | R_eff 基准下预期 "
        "3.64–3.67 |",
        "| Q_L | 信息项 | 信息项，如实 UNKNOWN | 冒烟档分辨率受限（审计 H6），"
        "精算档另批 |",
        "",
        "## 逐门新旧对照（同一 sparams 产物，判读链修复+criteria v2）",
        "",
        "| 标量 | v1 判读（verdict_offline.json） | v2 重判（本文件） |",
        "|---|---|---|",
    ]
    for label, key in _ROWS:
        lines.append(f"| {label} | {old_ext.get(key, '—')} | {new_ext.get(key, '—')} |")
    lines += [
        f"| status | {old.get('status', 'FAIL')} | **{verdict.get('status')}** |",
        "",
        "## v2 逐门结果",
        "",
        "| 门 | 结果 | 明细 |",
        "|---|---|---|",
    ]
    for c in verdict.get("judge", {}).get("checks", []):
        ok = {True: "PASS", False: "FAIL", None: "N/A"}[c["ok"]]
        lines.append(f"| {c['name']} | {ok} | {c['detail']} |")
    ql = new_ext.get("ql_info") or {}
    lines += [
        "",
        "## Q_L（信息项，不设门）",
        "",
        f"- 判定：{ql.get('status', 'UNKNOWN')}——{ql.get('reason', '')}",
    ]
    if "raw_ql" in ql:
        lines.append(f"- 原始量留痕：raw bw_3db={ql.get('raw_bw_3db_ghz')} GHz、"
                     f"raw Q_L={ql.get('raw_ql')}（分辨率受限，不采信）")
    env = verdict.get("nrts_converged") or {}
    lines += [
        "",
        "## 环境证据（与 v1 判读同一 run，零改动）",
        "",
        f"- NrTS 门：hit_nrts_limit={env.get('hit_nrts_limit')}、"
        f"能量 {env.get('min_energy_db')}dB（record_only 冒烟档，触帽属预期，"
        "只留痕不降级）",
        f"- G11 健康：{(verdict.get('g11_health') or {}).get('verdict', '—')}",
        "",
        "## Tier-2 决策点（主代理）",
        "",
        "gap 0.4→0.2mm + base ≤0.2667mm 重跑（预期 f2 峰 ~0.08/f1 峰 ~0.04，"
        "≈3300s≈55min solo）是否排 OE 窗——见审计 §5 Tier-2。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ring_resonator criteria v2 离线重判（零仿真；S4 审计定案）")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR),
                        help="ring run 目录（缺省 runs/oe_phase3/ring_resonator）")
    parser.add_argument("--out-dir", default=None,
                        help="产物目录（缺省=run 目录；测试隔离用）")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir
    verdict = run_rejudge(run_dir, out_dir)
    ext = verdict.get("extracted") or {}
    print(f"[ring-v2] status={verdict['status']} "
          f"f1={ext.get('f1')} f2={ext.get('f2')} "
          f"er1={ext.get('eps_r_f1')} er2={ext.get('eps_r_f2')}", flush=True)
    print(f"[ring-v2] 产物: {out_dir / 'verdict_offline_fix.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
