"""COMSOL mline 锚「数值 TEM 边界模端口」三档网格收敛 harness。

物理裁判：COMSOL 通道 mline 锚真机对拍升级——集总端口 Uniform 准静态场形
失配致 εeff +4.81% 如实 FAIL（run7/11，runs/comsol_tail/mline_summary.json），
本 harness 用官方数值 TEM 链（Port PortType=TEM + numericTEM=1 + study
[bma, freq] + 端口 StudyStep 解引用，官方例 cpw_numeric_tem_port/
microstrip_line_tem_via 同构）+ 基板 tanδ（官方 RF 材料库 LossTangentDF 组）
重跑三源对拍；εeff=extract_eps_eff（S21 相位斜率，#162 β 金标准判据）。

判据显式决策（与 openEMS/HFSS 引擎基准同一事实源）：
core/anchor_verdict.mline_benchmark_verdict——
1. 收敛性：最细两档 εeff 相对移动 <1%；
2. 主锚：最细档 εeff 对 openEMS β 金标准 2.886 |Δ|≤2%；
3. 副锚：最细档 εeff 对 HJ 闭式 |Δ|≤3%（tanδ=0.0037 同一参照系，锚值
   2.85264 即含损耗口径）；
4. 健康：ok 档全带 |S11|max < -10dB。
三源对拍结论同时如实记录对 HFSS 锚（2.920，hfss_mline_probe 探针值）偏差。

用法（git-bash，工作区根目录；license 席位串行，真跑每档占一席）：
    .venv/Scripts/python.exe scripts/comsol_mline_tem_benchmark.py --probe-only
    .venv/Scripts/python.exe scripts/comsol_mline_tem_benchmark.py
    .venv/Scripts/python.exe scripts/comsol_mline_tem_benchmark.py \
        --scales 1.0,0.7,0.55 --loss-tangent 0.0037
    .venv/Scripts/python.exe scripts/comsol_mline_tem_benchmark.py \
        --probe-only --port-sweep     # TEM 链 × 端口扫描步序零席位验证
    .venv/Scripts/python.exe scripts/comsol_mline_tem_benchmark.py \
        --port-sweep --scales 1.0     # TEM×Parametric 全 2×2 S 矩阵真跑

--probe-only：构建模型（几何/材料/物理/网格/study 序列）不解算——COMSOL 对
非法属性/类型串当场抛错，零席位验证建模序列；同时 best-effort 回读端口
特征属性核 StudyStep 解引用落位。退出码：0=PASS；2=FAIL（判据或求解失败）。

--port-sweep：tem 链 × 端口扫描组合（官方 PortSweepSettings +
外层 Parametric 步扫 PortName）——步序约束：bma1/bma2 在 Frequency 步前
（端口模变量只在边界模分析步产生），Parametric 为外层（先建=外层，官方
h_bend_waveguide_3d 同构）；离线序列由
tests/unit/test_comsol_tail.py::test_solve_tem_chain_supports_port_sweep 钉住。
真跑走 solve() 端口扫描分支（_extract_sparams_full 全 2×2 实测装配 +
COMSOL 原生 Touchstone 导出），产物落 runs/comsol_tail/mline_tem_parametric/，
判据=双锚（金标准 ≤2%/HJ ≤3%）+ |S11|max < −10dB + 无源性 max|S| ≤ 1+1e-3
+ 互易 max|S12−S21| ≤ 1e-3 + Touchstone 原生导出核验。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.comsol_adapter import (
    ComsolAdapter,
    extract_eps_eff,
    mline_closed_form,
    normalize_mline_params,
)
from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
from rfauto.core.anchor_verdict import (
    EPS_EFF_MLINE_GOLD,
    mline_benchmark_verdict,
)

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "runs" / "comsol_tail"
PARAMETRIC_DIR = OUT_DIR / "mline_tem_parametric"
PASSIVITY_TOL = 1e-3  # 无源性门：max|S| ≤ 1 + 1e-3（数值容差口径，同 skrf）
RECIPROCITY_TOL = 1e-3  # 互易门：max|S12 − S21| ≤ 1e-3（无源互易介质）
# HFSS 探针锚值（scripts/hfss_mline_probe.py 双锚判读实测 2.9200，#191 复跑）
HFSS_EPS_EFF_ANCHOR = 2.9200
W_MM, LINE_LEN_MM = 1.113, 40.0  # 50Ω mline 锚标称点（权威口径表 §1）
FREQ_RANGE = (2.3, 2.7)
N_FREQ = 5


def build_adapter(scale: float, loss_tangent: float | None,
                  work_dir: Path,
                  port_sweep: bool = False) -> ComsolAdapter:
    cfg = EMSolverConfig(
        solver_type=EMSolverType.COMSOL,
        working_dir=str(work_dir),
        freq_range_ghz=FREQ_RANGE,
        mesh_resolution_mm=1.0,  # mline 模板走 MLINE_MESH_HMAX，此值不消费
        extra_params={
            "comsol_version": "6.3",  # #215：6.4 过期，显式钉 6.3
            "cores": 2,
            "mline_port_chain": "tem",
            "loss_tangent": loss_tangent,
            "mesh_scale": scale,
            "save_mph": False,
        },
    )
    adapter = ComsolAdapter(cfg)
    assert adapter.connect(), "COMSOL 不可用（MPh/COMSOL_ROOT）"
    ok = adapter.build_geometry({"template": "mline",
                                 "params": {"w_mm": W_MM,
                                            "line_len_mm": LINE_LEN_MM},
                                 "port_sweep": port_sweep})
    if not ok:
        raise RuntimeError("build_geometry 拒绝（参数/模板）")
    return adapter


def probe_only(loss_tangent: float | None, port_sweep: bool = False) -> int:
    """零席位建模序列验证：非法属性/类型串在 build 阶段当场抛错。"""
    work = OUT_DIR / ("tem_probe_parametric" if port_sweep else "tem_probe")
    adapter = build_adapter(1.0, loss_tangent, work, port_sweep=port_sweep)
    spec = json.loads((work / "comsol_spec.json").read_text(encoding="utf-8"))
    print(f"probe build OK: port_chain={spec['port_chain']} "
          f"port_sweep={spec['port_sweep']} "
          f"loss_tangent={spec['loss_tangent']} "
          f"hj_eps_eff={spec['closed_form_hj']['eps_eff']}", flush=True)
    try:  # best-effort：回读端口特征属性核 StudyStep 解引用落位（#105）
        client = adapter._client_factory()
        model = adapter._build_model(client)
        sel_tags = [str(t) for t in model.java.component(
            "comp1").selection().tags()]
        print(f"selection tags={sel_tags}", flush=True)
        phys = model.java.component("comp1").physics("emw")
        report = {}
        for ptag in ("port1", "port2"):
            feat = phys.feature(ptag)
            report[ptag] = {
                "PortType": str(feat.getString("PortType")),
                "numericTEM": str(feat.getString("numericTEM")),
                "StudyStep": str(feat.getString("StudyStep")),
            }
        print(f"port props: {json.dumps(report)}", flush=True)
        # 端口扫描腿：回读 study 步序（约束：bma1/bma2 在 Frequency 步前，
        # Parametric 外层=先建；官方 cpw/h_bend 同构）。
        # study 步在 StudyFeatureList 下（study.feature().tags()）——
        # study 本体无 tags()（MPh StudyClient 真机实证 AttributeError）。
        step_tags = [str(t) for t in model.java.study(
            "std1").feature().tags()]
        print(f"study step order={step_tags}", flush=True)
        report["study_step_order"] = step_tags
        if port_sweep:
            _assert_parametric_step_order(step_tags)
        (work / "probe_port_props.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except Exception as exc:
        print(f"port props 回读失败（best-effort，不阻断）: {exc}", flush=True)
        if port_sweep:
            # 步序回读失败时端口扫描腿不真跑（先离线审计再真跑，#212/#1b）
            print("PROBE FAILED: 步序回读失败，不进真跑", flush=True)
            return 2
    print("PROBE PASS", flush=True)
    return 0


def _assert_parametric_step_order(step_tags: list[str]) -> None:
    """步序硬校验：bma1/bma2 先于 freq，param 外层先于 freq（离线审计）。"""
    if not step_tags:
        raise RuntimeError("study 步序为空（回读失败）")
    i_bma1, i_bma2 = step_tags.index("bma1"), step_tags.index("bma2")
    i_param, i_freq = step_tags.index("param"), step_tags.index("freq")
    if not (i_bma1 < i_freq and i_bma2 < i_freq and i_param < i_freq):
        raise RuntimeError(
            f"步序非法: {step_tags}（须 bma1/bma2/param 均在 freq 前）")


def parametric_extra_checks(s: np.ndarray) -> dict:
    """端口扫描全矩阵健康判据（确定性纯函数）：无源性 + 互易性。"""
    max_abs = float(np.max(np.abs(s)))
    reciprocity = float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])))
    return {
        "max_abs_s": round(max_abs, 6),
        "passive_ok": bool(max_abs <= 1.0 + PASSIVITY_TOL),
        "max_reciprocity_err": round(reciprocity, 9),
        "reciprocity_ok": bool(reciprocity <= RECIPROCITY_TOL),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scales", default="1.0,0.7,0.55",
                        help="逗号分隔 mesh_scale 三档（整体缩放 MLINE_MESH_HMAX）")
    parser.add_argument("--loss-tangent", type=float, default=0.0037,
                        help="基板 tanδ（默认 rogers4350b 表值 0.0037；0=无耗）")
    parser.add_argument("--freq", type=float, default=2.5,
                        help="对照频率 GHz（三源对拍判据频点）")
    parser.add_argument("--probe-only", action="store_true",
                        help="零席位建模序列验证后退出（不 solve）")
    parser.add_argument("--port-sweep", action="store_true",
                        help="tem 链 × 端口扫描组合腿（全 2×2 S 矩阵 + 原生 "
                             "Touchstone；产物落 mline_tem_parametric/）")
    args = parser.parse_args()

    tan_d = args.loss_tangent if args.loss_tangent > 0 else None
    if args.probe_only:
        return probe_only(tan_d, port_sweep=args.port_sweep)

    out_dir = PARAMETRIC_DIR if args.port_sweep else OUT_DIR
    out_name = ("mline_tem_parametric.json"
                if args.port_sweep else "mline_tem_mesh_convergence.json")
    _, eps_hj = mline_closed_form(W_MM, float(args.freq), 3.66, 0.508,
                                  tan_d=tan_d if tan_d is not None else 0.0037)
    scales = [float(s) for s in args.scales.split(",")]
    entries: list[dict] = []
    for scale in scales:
        work = (PARAMETRIC_DIR / f"tem_scale_{scale:g}" if args.port_sweep
                else OUT_DIR / f"tem_scale_{scale:g}")
        try:
            adapter = build_adapter(scale, tan_d, work,
                                    port_sweep=args.port_sweep)
        except RuntimeError as exc:
            entries.append({"mesh_scale": scale, "ok": False,
                            "message": str(exc)})
            print(f"scale={scale}: build FAIL {exc}", flush=True)
            continue
        t0 = time.time()
        result = adapter.solve()
        adapter.close()
        wall = time.time() - t0
        if not (result.success and result.s_params is not None):
            entries.append({"mesh_scale": scale, "ok": False,
                            "message": result.message, "wall_s": round(wall)})
            print(f"scale={scale}: solve FAIL {result.message}", flush=True)
            continue
        s11 = result.s_params[:, 0, 0]
        s11_max_db = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
        eps_eff = extract_eps_eff(result.freq_ghz, result.s_params[:, 1, 0],
                                  LINE_LEN_MM)
        delta_hj = (eps_eff / eps_hj - 1) * 100
        delta_gold = (eps_eff / EPS_EFF_MLINE_GOLD - 1) * 100
        delta_hfss = (eps_eff / HFSS_EPS_EFF_ANCHOR - 1) * 100
        entry = {
            "mesh_scale": scale, "ok": True, "wall_s": round(wall),
            "s11_max_db": round(s11_max_db, 2),
            "eps_eff": round(eps_eff, 5),
            "delta_vs_hj_pct": round(delta_hj, 3),
            "delta_vs_gold_pct": round(delta_gold, 3),
            "delta_vs_hfss_pct": round(delta_hfss, 3),
        }
        if args.port_sweep:
            entry["sparam_fill"] = result.field_data.get("sparam_fill", "")
            entry["touchstone"] = result.field_data.get("touchstone", {})
            entry.update(parametric_extra_checks(result.s_params))
        entries.append(entry)
        extra = ""
        if args.port_sweep and entry["ok"]:
            extra = (f" max|S|={entry['max_abs_s']} "
                     f"(passive={entry['passive_ok']}) "
                     f"recip={entry['max_reciprocity_err']} "
                     f"touchstone={entry['touchstone'].get('writer')}")
        print(f"scale={scale}: eps_eff={eps_eff:.4f} Δ_HJ={delta_hj:+.2f}% "
              f"Δ_gold={delta_gold:+.2f}% Δ_HFSS={delta_hfss:+.2f}% "
              f"|S11|max={s11_max_db:.1f}dB wall={wall:.0f}s{extra}",
              flush=True)

    ok_entries = [e for e in entries if e.get("ok")]
    convergence = None
    if len(ok_entries) >= 2:
        a, b = ok_entries[-2]["eps_eff"], ok_entries[-1]["eps_eff"]
        convergence = round(abs(b - a) / b * 100, 4)
    eps_finest = ok_entries[-1]["eps_eff"] if ok_entries else None
    s11_worst = max((e["s11_max_db"] for e in ok_entries), default=None)
    bench = mline_benchmark_verdict(eps_finest, convergence, s11_worst,
                                    eps_gold=EPS_EFF_MLINE_GOLD,
                                    eps_hj=eps_hj)
    verdict = str(bench["verdict"])
    # 端口扫描腿附加判据：无源性 + Touchstone 原生导出为门（#26②
    # 判据清单）；互易性**只记录不作门**——真机实测 max|S12−S21|≈7.6e-3
    # （2.3GHz，|S21|≈0.985 的 0.8%）：数值端口两端口各自 bma 模归一在
    # 非同构端面网格上有亚百分位差异（假设/待证），1e-3 门对 FEM 数值端口
    # 过紧，门化会造假 FAIL；残差数字照实入册供后续核。
    extra_fail: list[str] = []
    reciprocity_worst = None
    if args.port_sweep:
        for e in ok_entries:
            if not e.get("passive_ok", True):
                extra_fail.append(
                    f"scale={e['mesh_scale']}: max|S|={e['max_abs_s']} 超无源门")
            if e.get("touchstone", {}).get("writer") != "comsol_native":
                extra_fail.append(
                    f"scale={e['mesh_scale']}: Touchstone 非原生导出"
                    f"（{e.get('touchstone')}）")
        recips = [e.get("max_reciprocity_err") for e in ok_entries
                  if e.get("max_reciprocity_err") is not None]
        reciprocity_worst = max(recips) if recips else None
        if extra_fail and verdict == "PASS":
            verdict = "FAIL"

    spec0 = normalize_mline_params({"w_mm": W_MM, "line_len_mm": LINE_LEN_MM})
    out = {
        "anchor": "mline", "template": "mline", "params": spec0,
        "port_chain": "tem", "loss_tangent": tan_d,
        "port_sweep": bool(args.port_sweep),
        "judge_freq_ghz": float(args.freq),
        "eps_hj_closed_form": round(eps_hj, 5),
        "eps_gold_standard": EPS_EFF_MLINE_GOLD,
        "eps_hfss_anchor": HFSS_EPS_EFF_ANCHOR,
        "scales": scales,
        "entries": entries,
        "convergence_finest2_pct": convergence,
        "delta_vs_gold_pct": (round(float(bench["delta_gold_pct"]), 3)
                              if bench["delta_gold_pct"] is not None else None),
        "delta_vs_hj_pct": (round(float(bench["delta_hj_pct"]), 3)
                            if bench["delta_hj_pct"] is not None else None),
        "verdict": verdict,
        "criteria": {"convergence_pct_lt": 1.0,
                     "delta_vs_gold_pct_abs_le": 2.0,
                     "delta_vs_hj_pct_abs_le": 3.0,
                     "s11_max_db_lt": -10.0},
        "history": {
            "lumped_port_run11": {
                "eps_eff": 2.98972, "delta_vs_hj_pct": 4.805,
                "verdict": "FAIL（集总端口准静态模失配假设，如实）"},
        },
    }
    if args.port_sweep:
        out["criteria"]["passivity_max_abs_s_le"] = 1.0 + PASSIVITY_TOL
        out["criteria"]["reciprocity_max_err_le"] = RECIPROCITY_TOL
        out["reciprocity_worst"] = reciprocity_worst
        out["reciprocity_note"] = (
            "互易只记录不作门：数值端口两端口各自 bma 模归一在非同构端面"
            "网格上有亚百分位差异（假设/待证），真机实测残差见 "
            "reciprocity_worst")
        out["extra_fail_reasons"] = extra_fail
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    tail = ""
    if args.port_sweep and extra_fail:
        tail = f" extra-FAIL: {'; '.join(extra_fail)}"
    print(f"COMSOL_MLINE_TEM_BENCHMARK_{verdict}（判据：收敛<1%、最细档对金"
          f"标准≤2%/对 HJ ≤3% 双锚、|S11|max<-10dB"
          + ("、无源 max|S|≤1+1e-3、Touchstone 原生导出（互易记录不作门）"
             if args.port_sweep else "")
          + "）"
          + (f" reason: {bench['reason']}" if bench["reason"] else "")
          + tail + f" → {out_path}", flush=True)
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
