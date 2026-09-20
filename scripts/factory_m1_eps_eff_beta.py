"""M1 数据集 eps_eff 列修复：β 口径重导（参考面无关，零重仿真）。

发现：compute_point_metrics 的
eps_eff_mean_in_band 用 S21 解缠相位斜率 × L=line_len_mm=40mm，但 mline 模板
S21 参考面在板缘端口面（port_ut_1A start-coordinates y=−47.7mm，非 ±20mm
线端）——斜率对应总电跨度 ~93.2mm（含馈段），L=40mm 语义下 εeff 系统性
虚大 ~5.4×（120 点中位 15.98 vs 物理 ~2.9）。

修复：每点从归档 port_beta.csv（引擎 CalcPort，局部传播常数，与参考面
无关，#301 口径）带内 (2.4-2.6GHz) 中位 β → eps_eff_beta_mean_in_band
= (β·c/ω)²；并列 zl1_re/zl2_re 带内中位（Z0(w) 消费列）。旧列保留不删，
note 记失效语义；重物化数据集。

用法（cwd=仓根）：python scripts/factory_m1_eps_eff_beta.py [--dry-run]
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
C0 = 299792458.0
BAND = (2.4e9, 2.6e9)
INDEX = REPO / "runs" / "data_factory_m1" / "points_index.json"


def derive_point(eval_dir: Path) -> dict:
    """从 eval 目录 port_beta.csv 导 β 口径 εeff 与带内 ZL（纯函数面）。"""
    pb = eval_dir / "port_beta.csv"
    if not pb.exists():
        return {"ok": False, "msg": f"缺 {pb}"}
    rows = list(csv.DictReader(pb.read_text(encoding="utf-8").splitlines()))
    band = [r for r in rows
            if BAND[0] <= float(r["freq_hz"]) <= BAND[1]]
    if not band:
        return {"ok": False, "msg": "带内无频点"}
    betas: list[float] = []
    zl1: list[float] = []
    zl2: list[float] = []
    for r in band:
        for key in ("beta_rad_per_m", "beta2_rad_per_m"):
            v = r.get(key)
            if v not in (None, ""):
                betas.append(float(v))
        for key, out in (("re_zl1_ohm", zl1), ("re_zl2_ohm", zl2)):
            v = r.get(key)
            if v not in (None, ""):
                out.append(float(v))
    beta_med = statistics.median(betas)
    f_med = statistics.median(float(r["freq_hz"]) for r in band)
    eps_beta = (beta_med * C0 / (2 * 3.141592653589793 * f_med)) ** 2
    return {"ok": True, "eps_eff_beta": eps_beta,
            "beta_med_rad_per_m": beta_med,
            "zl1_re_med": statistics.median(zl1) if zl1 else None,
            "zl2_re_med": statistics.median(zl2) if zl2 else None,
            "n_band_points": len(band)}


def _w_fingerprint(w: float) -> int:
    return round(float(w) * 1e6)


def build_eval_w_map(evals_root: Path) -> dict[int, float]:
    """eval_NNNN → w_mm（渲染脚本 `W = <val> * 1e-3` 行，确定性匹配）。"""
    import re

    out: dict[int, float] = {}
    for d in sorted(evals_root.glob("eval_*")):
        sim = d / "simulation.py"
        if not sim.exists():
            continue
        m = re.search(r"^W = ([0-9.eE+-]+) \* 1e-3", sim.read_text(encoding="utf-8"),
                      re.MULTILINE)
        if m:
            out[int(d.name.split("_")[1])] = float(m.group(1))
    return out


def main(argv: list[str] | None = None) -> int:
    dry = "--dry-run" in (argv or sys.argv[1:])
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    eval_w = build_eval_w_map(REPO / "runs" / "data_factory_m1" / "evals")
    eps_vals: list[float] = []
    n_ok = 0
    for pid in sorted(idx):
        row = idx[pid]
        if row.get("status") != "done":
            continue
        w = float(row["w_mm"])
        eval_n = next((n for n, v in eval_w.items()
                       if _w_fingerprint(v) == _w_fingerprint(w)), None)
        if eval_n is None:
            print(f"[fix] {pid}: evals 中找不到 w={w} 的渲染")
            continue
        eval_dir = REPO / "runs" / "data_factory_m1" / "evals" / f"eval_{eval_n:04d}"
        res = derive_point(eval_dir)
        if not res["ok"]:
            print(f"[fix] {pid}: {res['msg']}")
            continue
        rid = row["rid"]
        run_dir = REPO / "runs" / rid
        mj_path = run_dir / "results" / "metrics.json"
        mj = json.loads(mj_path.read_text(encoding="utf-8"))
        note = ("eps_eff_beta_mean_in_band=引擎 CalcPort β 带内中位 → (β·c/ω)²，"
                "参考面无关（#301）；eps_eff_mean_in_band 为 S21 相位斜率×L=40mm，"
                "但参考面在板缘端口面（port_ut start-coordinates y=∓47.7mm，"
                "总电跨度 ~93mm 含馈段），L 语义失效（虚大 ~5.4×）只留档不消费")
        if not dry and "eps_eff_beta_mean_in_band" not in mj["metrics"]:
                mj["metrics"]["eps_eff_beta_mean_in_band"] = res["eps_eff_beta"]
                mj["metrics"]["zl1_re_ohm_med_in_band"] = res["zl1_re_med"]
                mj["metrics"]["zl2_re_ohm_med_in_band"] = res["zl2_re_med"]
                if "eps_eff_beta_note" not in (mj.get("notes") or []):
                    mj.setdefault("notes", []).append(note)
                mj_path.write_text(
                    json.dumps(mj, ensure_ascii=False, indent=1), encoding="utf-8")
        eps_vals.append(res["eps_eff_beta"])
        n_ok += 1
        if n_ok <= 5 or n_ok % 40 == 0:
            print(f"[fix] {pid} w={w:.3f} eval={eval_n:04d} "
                  f"eps_eff_beta={res['eps_eff_beta']:.4f} "
                  f"zl1={res['zl1_re_med']:.1f} zl2={res['zl2_re_med']:.1f}")
    if eps_vals:
        print(f"[fix] n={n_ok} eps_eff_beta min/med/max="
              f"{min(eps_vals):.4f}/{statistics.median(eps_vals):.4f}/{max(eps_vals):.4f}")
    if dry:
        print("[fix] dry-run：未写任何文件")
        return 0
    from rfauto.service.dataset_service import materialize_dataset
    rids = [row["rid"] for _, row in sorted(idx.items())
            if row.get("status") == "done"]
    mat = materialize_dataset(run_ids=rids, name="datafactory_m1_mline_20260919",
                              health_gate=True)
    print(f"[fix] 重物化 ok={mat.get('ok')} rows={mat.get('n_rows')} "
          f"unhealthy={mat.get('unhealthy_runs')}")
    return 0 if mat.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
