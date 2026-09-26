"""DP-1 P3 G1——MMT 侧产物生成（HFSS 仲裁对拍输入；判据
runs/df6_dp1p3/criteria.md §2，先写后跑 #122）。

三链（与 HFSS 侧同几何字面量/同频网 8–12GHz 201 点）：
  straight : [uniform 22.86×10.16×20.0]
  iris_t0  : [uniform 10.0, iris(d=16.0, t=0), uniform 10.0]
  iris_t1  : 同上 t=1.0
服务入口 solve_mmt（经全局注册表，JSON 进出；#4）；产物三件落
runs/df6_dp1p3/mmt/<case>/（sparams.csv/mmt.s2p/mmt_meta.json）。
undetermined 频点（膜片子波导近截止带）S=null 如实，对拍只在
determined 点判（criteria §2）。禁手抄数字（草案纪律）——判读脚本
直读 mmt_meta.json。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs" / "df6_dp1p3"

A_MM, B_MM = 22.86, 10.16          # WR-90（与 P2 判据/发射草案同源字面量）
D_MM = 16.00                        # d/a=0.700（草案字面）
X0_MM = (A_MM - D_MM) / 2.0         # 3.43
L_HALF_MM = 10.0                    # 端口面到膜片
N_FREQ = 201
F_LO, F_HI = 8.0, 12.0
N_MODES_REF = 21                    # 草案起步值

FREQS = [round(F_LO + (F_HI - F_LO) * i / (N_FREQ - 1), 10)
         for i in range(N_FREQ)]


def _uniform(length_mm: float) -> dict:
    return {"type": "uniform", "a_mm": A_MM, "b_mm": B_MM,
            "length_mm": length_mm}


def _payload(thickness_mm: float | None) -> dict:
    sections = [] if thickness_mm is None else \
        [_uniform(L_HALF_MM),
         {"type": "iris", "a_mm": A_MM, "b_mm": B_MM,
          "aperture_mm": D_MM, "thickness_mm": thickness_mm},
         _uniform(L_HALF_MM)]
    if thickness_mm is None:
        sections = [_uniform(20.0)]
    return {"sections": sections, "freqs_ghz": FREQS,
            "mode_policy": {"n_modes_ref": N_MODES_REF}}


def main() -> int:
    from rfauto.service.mmt_service import solve_mmt

    OUT.mkdir(parents=True, exist_ok=True)
    cases = {"straight": _payload(None),
             "iris_t0": _payload(0.0),
             "iris_t1": _payload(1.0)}
    inputs_echo: dict = {"freqs_ghz": FREQS, "n_freq": N_FREQ,
                         "n_modes_ref": N_MODES_REF,
                         "geometry": {"a_mm": A_MM, "b_mm": B_MM,
                                      "d_mm": D_MM, "x0_mm": X0_MM,
                                      "l_half_mm": L_HALF_MM},
                         "cases": {}}
    failed: list[str] = []
    for case, payload in cases.items():
        work = OUT / "mmt" / case
        work.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        res = solve_mmt(payload, work_dir=work)
        wall = round(time.time() - t0, 3)
        if not res.get("ok"):
            failed.append(case)
            print(f"[{case}] FAIL: {res.get('errors')}", flush=True)
            continue
        n_det = res["n_determined"]
        n_und = res["n_undetermined"]
        print(f"[{case}] ok wall={wall}s determined={n_det}/{n_det + n_und} "
              f"converged={res['converged']} "
              f"undet_band=[{min(res['undetermined_freqs_ghz'], default=float('nan')):.4g}"
              f"..{max(res['undetermined_freqs_ghz'], default=float('nan')):.4g}GHz] "
              f"work={work}", flush=True)
        inputs_echo["cases"][case] = {
            "sections": payload["sections"], "wall_time_s": wall,
            "n_determined": n_det, "n_undetermined": n_und,
            "converged": res["converged"],
            "undetermined_freqs_ghz": res["undetermined_freqs_ghz"],
            "artifacts": res["artifacts"],
        }
    (OUT / "mmt" / "inputs.json").write_text(
        json.dumps(inputs_echo, ensure_ascii=False, indent=2),
        encoding="utf-8")
    if failed:
        print(f"MMT_SIDE_FAIL cases={failed}", flush=True)
        return 1
    print("MMT_SIDE_OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
