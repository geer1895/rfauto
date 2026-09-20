"""AFS 自适应频扫真机验收 harness（冻结判据）。

判据（预声明原文："频点数减半且 vs 全扫 FSV >= VG"，
core/afs.py:303 已按此预置 ``vs_full.fsv.at_least_vg``）：
    status == "converged" 且 summary["vs_full"]["fsv"]["at_least_vg"] 为真
    且 reduction_ratio >= 0.5（reduction_ratio = 1 - n_solves / n_full，
    n_full=全扫密集参考点数——"频点数减半"语义即 n_solves <= n_full/2）。

案例（mline TEM 链，同 runs/comsol_tail/mline_tem_mesh_convergence.json
真机过锚模型）：50Ω 微带线（skrf HJ 综合 W=1.113mm@rogers4350b）、带
2.3-2.7 GHz、mesh_scale=1.0、comsol_version="6.3" 钉版本（#215）、基板
tanδ=0.0037（rogers4350b 表值，官方 LossTangentDF 组；与 tem benchmark 同
参照系，HJ 锚 2.85264 即含损耗口径）。
S21 取复数（幅度 ~0dB、好条件数）；S11 在 −40dB 底噪附近不适合拟合，不进
AFS（如实记录于 verdict）。

**离线审计先行（#212/#1b，tests/unit/test_comsol_close_bundle.py 钉住）**：
FSV 裁判按 |S| dB 口径、ADM/FDM 以 (|Lo1|+|Lo2|) 均值归一——**纯无耗**匹配
线 |S21| dB 恒 ≈ 0（合成实测跨带 8e-8 dB），参考近零时任何模型误差都成
O(1) 相对量 → 结构性 VP（#195 同族"常数陷阱"，与 tol 无关）；而真实量级
损耗（|S21|≈−0.05 dB、跨带 ~0.01 dB）下 VF 模型幅度误差仅 ~6e-4 dB（线性
1e-2 容差几乎全落在相位）→ FSV Ex。故真机案例必须建 tanδ（物理真实且判据
非退化），无耗变体只作为退化边界离线留证。tol 维持内核默认 1e-2：更紧
（5e-3）时 (4,8) 阶梯拟合不了纯延迟线 → max_points 未收敛（离线实测）。

流程（license 席位串行，建模一次）：
  1. 密集全扫参考：freq 步 plist 一次写满 n_full 点（默认 41），study run
     一次、EvalGlobal 一次取全部频点（1 席）→ runs/.../afs_realcase/
     full_scan.json；
  2. afs_sample(evaluate=持久模型单频重解回调（comsol_adapter.
     resolve_s21_at_frequency），full_response=全扫复数线性插值，
     n_dense=n_full 对齐真实全扫点数)——每个回调一次单频求解（1 席时
     间），建模/网格零重建；
  3. verdict 纯函数判定（judge_afs），未收敛/FSV 不到 VG/缩减不足一律如实
     FAIL，不重试凑绿（#122）。

离线门（零真机）：tests/unit/test_comsol_close_bundle.py——合成回调跑
run_afs_core 全链、judge_afs 判据边界、未收敛诚实路径、单频重解 Java 序列。

用法（git-bash，工作区根目录）：
    .venv/Scripts/python.exe scripts/comsol_afs_realcase.py --dry-run
    .venv/Scripts/python.exe scripts/comsol_afs_realcase.py
    .venv/Scripts/python.exe scripts/comsol_afs_realcase.py --n-full 41

退出码：0=PASS；2=判据 FAIL（verdict 已落盘，不伪装绿）；3=环境不可用。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.comsol_adapter import (
    MLINE_MESH_HMAX,
    ComsolAdapter,
    mline_closed_form,
    normalize_mline_params,
)
from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
from rfauto.core.afs import afs_sample

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "runs" / "comsol_tail" / "afs_realcase"
W_MM, LINE_LEN_MM = 1.113, 40.0  # 50Ω mline 锚标称点（权威口径表 §1）
FREQ_RANGE_GHZ = (2.3, 2.7)
REDUCTION_RATIO_MIN = 0.5  # §10.20⑩ "频点数减半"
LOSS_TANGENT_DEFAULT = 0.0037  # rogers4350b 表值（tem benchmark 同参照系）


# ── 判定（确定性纯函数，离线可测）─────────────────────────────────────────────

def judge_afs(summary: dict, *,
              reduction_ratio_min: float = REDUCTION_RATIO_MIN) -> dict:
    """afs_sample summary → §10.20⑩ 冻结判据 verdict（确定性纯函数）。

    PASS 三条同时成立：converged、vs_full.fsv.at_least_vg（FSV GDM 等级
    下标 <=1 即 >= VG）、reduction_ratio >= 0.5。任一不成立如实 FAIL。
    """
    vs = summary.get("vs_full")
    reasons: list[str] = []
    converged = bool(summary.get("converged"))
    if not converged:
        reasons.append(f"AFS 未收敛（status={summary.get('status')}）")
    fsv = (vs or {}).get("fsv", {})
    at_least_vg = bool(fsv.get("at_least_vg"))
    if vs is None:
        reasons.append("summary 缺 vs_full（未提供全扫参考）")
    elif not at_least_vg:
        reasons.append(
            f"vs 全扫 FSV 等级不足 VG（gdm={fsv.get('gdm_mean')}, "
            f"grade={fsv.get('gdm_grade')}）")
    reduction = float((vs or {}).get("reduction_ratio", 0.0))
    if vs is None:
        pass
    elif reduction < reduction_ratio_min:
        reasons.append(
            f"缩减比 {reduction:.4f} < {reduction_ratio_min} "
            f"(n_solves={vs.get('n_solves')} vs n_full={vs.get('n_full')})")
    return {
        "verdict": "PASS" if not reasons else "FAIL",
        "criteria": {
            "converged": converged,
            "at_least_vg": at_least_vg,
            "reduction_ratio": reduction,
            "reduction_ratio_min": reduction_ratio_min,
        },
        "reasons": reasons,
    }


def full_scan_interpolator(freqs_ghz: np.ndarray,
                           s21: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    """全扫复数 S21 的线性插值器（afs_sample full_response 口径）。"""
    f_axis = np.asarray(freqs_ghz, dtype=float)

    def response(freqs_hz: np.ndarray) -> np.ndarray:
        f_ghz = np.asarray(freqs_hz, dtype=float) / 1e9
        return np.interp(f_ghz, f_axis, s21.real) + 1j * np.interp(
            f_ghz, f_axis, s21.imag)

    return response


def run_afs_core(evaluate: Callable[[float], complex],
                 full_response: Callable[[np.ndarray], np.ndarray],
                 f_min_hz: float, f_max_hz: float, *, n_full: int,
                 max_points: int | None = None,
                 tol: float | None = None) -> dict:
    """afs_sample 包装（n_dense=n_full 对齐真实全扫点数；离线门走合成回调）。"""
    kwargs: dict = {"n_dense": int(n_full), "full_response": full_response}
    if max_points is not None:
        kwargs["max_points"] = int(max_points)
    if tol is not None:
        kwargs["tol"] = float(tol)
    return afs_sample(evaluate, float(f_min_hz), float(f_max_hz), **kwargs)


# ── 真机路径 ─────────────────────────────────────────────────────────────────

def build_adapter(scale: float, work_dir: Path, freqs_ghz: list[float],
                  loss_tangent: float | None) -> ComsolAdapter:
    cfg = EMSolverConfig(
        solver_type=EMSolverType.COMSOL,
        working_dir=str(work_dir),
        freq_range_ghz=FREQ_RANGE_GHZ,
        mesh_resolution_mm=1.0,  # mline 模板走 MLINE_MESH_HMAX，此值不消费
        extra_params={
            "comsol_version": "6.3",  # #215：6.4 license 过期，显式钉 6.3
            "cores": 2,
            "mline_port_chain": "tem",  # TEM 边界模端口链（真机过锚口径）
            "loss_tangent": loss_tangent,  # 判据非退化前提（模块 docstring）
            "mesh_scale": scale,
            "save_mph": False,
        },
    )
    adapter = ComsolAdapter(cfg)
    assert adapter.connect(), "COMSOL 不可用（MPh/COMSOL_ROOT）"
    ok = adapter.build_geometry({"template": "mline",
                                 "params": {"w_mm": W_MM,
                                            "line_len_mm": LINE_LEN_MM,
                                            "freq_ghz": freqs_ghz}})
    assert ok, "build_geometry 拒绝（参数/模板）"
    return adapter


def real_run(n_full: int, scale: float, loss_tangent: float | None) -> int:
    """真机：全扫参考 1 席 + AFS 选点重解（持久模型，串行）。"""
    freqs_ghz = [round(f, 6) for f in
                 np.linspace(*FREQ_RANGE_GHZ, int(n_full))]
    freqs_hz = [f * 1e9 for f in freqs_ghz]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    adapter = build_adapter(scale, OUT_DIR, freqs_ghz, loss_tangent)
    print(f"model built (mesh_scale={scale}, tan_d={loss_tangent}, "
          f"hmax={MLINE_MESH_HMAX}) -> solving full scan "
          f"{freqs_ghz[0]}..{freqs_ghz[-1]} GHz x{n_full}", flush=True)
    result = adapter.solve()
    if not (result.success and result.s_params is not None):
        print(f"FULL SCAN FAIL: {result.message}", flush=True)
        (OUT_DIR / "verdict.json").write_text(json.dumps(
            {"verdict": "FAIL", "reasons": [f"全扫求解失败: {result.message}"],
             "n_full": n_full}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return 2
    full_s = time.time() - t0
    s21_full = np.asarray(result.s_params[:, 1, 0], dtype=complex)
    s11_max_db = float(np.max(20 * np.log10(np.abs(
        result.s_params[:, 0, 0]) + 1e-12)))
    # 健康审计先行（#212/#1b）：|S21| 幅度近 0dB 才适合做拟合对象；S11 深底噪
    # 不进 AFS（如实记录，不改判据）。
    s21_mag_db = 20 * np.log10(np.abs(s21_full) + 1e-12)
    print(f"full scan ok ({full_s:.0f}s): |S21| {s21_mag_db.min():.2f}.."
          f"{s21_mag_db.max():.2f} dB, |S11|max {s11_max_db:.1f} dB",
          flush=True)
    (OUT_DIR / "full_scan.json").write_text(json.dumps({
        "freq_ghz": freqs_ghz,
        "s21": [[float(v.real), float(v.imag)] for v in s21_full],
        "s11_max_db": round(s11_max_db, 2),
        "port_chain": adapter._port_chain,
        "loss_tangent": loss_tangent,
        "mesh_scale": scale,
        "wall_s": round(full_s, 1),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    model = adapter._model
    solves: list[float] = []

    def evaluate(f_hz: float) -> complex:
        t1 = time.time()
        val = adapter.resolve_s21_at_frequency(model, f_hz / 1e9)
        solves.append(time.time() - t1)
        print(f"  afs solve #{len(solves)} @ {f_hz / 1e9:.4f} GHz -> "
              f"|S21|={20 * np.log10(abs(val) + 1e-12):+.3f} dB "
              f"({time.time() - t1:.1f}s)", flush=True)
        return val

    summary = run_afs_core(
        evaluate, full_scan_interpolator(freqs_ghz, s21_full),
        freqs_hz[0], freqs_hz[-1], n_full=n_full)
    summary["evaluate_wall_s"] = [round(s, 2) for s in solves]
    (OUT_DIR / "afs_summary.json").write_text(json.dumps(
        summary, ensure_ascii=False, indent=1), encoding="utf-8")

    verdict = judge_afs(summary)
    _, eps_hj = mline_closed_form(W_MM, float(np.median(freqs_ghz)), 3.66,
                                  0.508,
                                  tan_d=loss_tangent if loss_tangent is not None
                                  else 0.0037)
    verdict.update({
        "case": "mline_tem_afs",
        "n_full": n_full,
        "freq_range_ghz": list(FREQ_RANGE_GHZ),
        "mesh_scale": scale,
        "loss_tangent": loss_tangent,
        "eps_hj_closed_form": round(eps_hj, 5),
        "s11_max_db_full_scan": round(s11_max_db, 2),
        "note_s11": ("S11 在 -40dB 底噪附近，不进 AFS（拟合对象=复数 S21，"
                     "幅度 ~0dB 好条件数）"),
        "note_fsv_morphology": (
            "FSV 按 |S| dB 归一：tanδ 必建（无耗参考 dB≈0 时 ADM/FDM 结构性 "
            "退化 → VP，离线合成实证，#195 同族常数陷阱）；tol=内核默认 "
            "1e-2（更紧则延迟线拟合触 max_points，离线实测）"),
        "full_scan_wall_s": round(full_s, 1),
        "generated_by": "scripts/comsol_afs_realcase.py",
    })
    (OUT_DIR / "verdict.json").write_text(json.dumps(
        verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    vs = summary["vs_full"]
    print(f"AFS {verdict['verdict']}: n_solves={vs['n_solves']}/"
          f"{n_full} reduction={vs['reduction_ratio']:.3f} "
          f"FSV={vs['fsv']['gdm_grade']}({vs['fsv']['gdm_mean']:.4f}) "
          f"reasons={verdict['reasons']}", flush=True)
    return 0 if verdict["verdict"] == "PASS" else 2


def dry_run(n_full: int, scale: float, loss_tangent: float | None) -> int:
    spec = normalize_mline_params({"w_mm": W_MM, "line_len_mm": LINE_LEN_MM})
    freqs = [round(f, 6) for f in np.linspace(*FREQ_RANGE_GHZ, int(n_full))]
    print(json.dumps({
        "mode": "dry-run", "template": "mline", "port_chain": "tem",
        "params": spec, "freq_ghz": freqs, "mesh_scale": scale,
        "loss_tangent": loss_tangent,
        "mesh_hmax_mm": MLINE_MESH_HMAX,
        "criterion": {"converged": True,
                      "at_least_vg": "core/afs.py vs_full.fsv.at_least_vg",
                      "reduction_ratio_min": REDUCTION_RATIO_MIN},
        "out_dir": str(OUT_DIR),
    }, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n-full", type=int, default=41,
                        help="密集全扫参考点数（默认 41）")
    parser.add_argument("--mesh-scale", type=float, default=1.0)
    parser.add_argument("--loss-tangent", type=float,
                        default=LOSS_TANGENT_DEFAULT,
                        help="基板 tanδ（默认 rogers4350b 表值 0.0037；"
                             "0=无耗——FSV 平线退化，仅离线审计用）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只输出计划（参数/频轴/判据），不启 COMSOL")
    args = parser.parse_args(argv)
    if args.n_full < 5:
        parser.error("--n-full 至少 5")
    tan_d = args.loss_tangent if args.loss_tangent > 0 else None
    if args.dry_run:
        return dry_run(args.n_full, args.mesh_scale, tan_d)
    return real_run(args.n_full, args.mesh_scale, tan_d)


if __name__ == "__main__":
    sys.exit(main())
