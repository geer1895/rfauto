"""B6 stage-2 冒烟：zone 深化提取 → 确定性代理寻优 → openEMS 真板抽查。

链路（§10.2 B6 stage-2 口径，stage-1 锚腿已达成基础上的深化闭环）：

1. build_demo_cpwg_pcb 生成 CPWG demo 板（w=0.849/L=40/rogers4350b）；
2. extract_pcb 提取走线 + **zone（gap=clearance，stage-2 zone 深化）**
   + footprint/pad（往返锚由 tests/unit/test_kicad_extract.py 钉死）；
3. service/kicad_em_service.optimize_cpw_from_extract：提取参数 →
   CPWG 共形映射闭式代理（core/calculators._cpwg_ri）→ Z0 判据 +
   synthesize_cpw_model 寻优 w*（确定性内核，无 LLM）；
4. autotune_recipe_from_extract 落盘配方（接优化环文件面，autotune_loop
   可直接消费）；
5. openEMS 真跑抽查（锚腿 mesh 0 = smoke_cpw_anchor/pt4 判据口径）：
   **喂提取+zone 链路出的参数**（gap 不再取常量，出自板内 zone
   clearance）→ β 金标准 εeff 对照闭式 + |S11| 判废线。stage-1 锚腿
   基线：εeff 2.5173（−1.95%）、|S11|max −22.5dB（runs/
   kicad_extract_smoke/smoke_run.log）。

判据（逐条打印 KICAD_B6_S2_*）：
- OPTIMIZER：|z0_extracted − 50| ≤ 2Ω 且 |w* − w_extracted| ≤ 0.02mm
- EM_ANCHOR：|S11|max < −10dB 且 |Δεeff| ≤ 2%（β 金标准，#162/#189）

真机纪律：openEMS 同一时刻全机只此一个真跑（先查进程）；串行单腿。
"""
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.kicad_extract import (
    DEMO_GAP_MM,
    DEMO_W_MM,
    build_demo_cpwg_pcb,
    extract_pcb,
)
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.core.calculators import _cpwg_ri
from rfauto.service.kicad_em_service import (
    autotune_recipe_from_extract,
    optimize_cpw_from_extract,
)

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "runs" / "kicad_b6_stage2"
WORK.mkdir(parents=True, exist_ok=True)
PCB = WORK / "demo_cpwg.kicad_pcb"
FREQ_RANGE = (2.25, 2.75)


def _fail(msg: str) -> None:
    print(f"KICAD_B6_S2_FAIL（{msg}）")
    sys.exit(1)


def _eps_from_beta(port_beta_csv: Path) -> tuple[float, float]:
    """β 金标准（#162/#189 同法）：CalcPort 自算 β → εeff（带内中位）。"""
    with open(port_beta_csv, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bbeta = np.array([float(r[1]) for r in rows])
    sel = (bf >= 2.4e9) & (bf <= 2.6e9)
    beta_med = float(np.median(bbeta[sel]))
    f_med = float(np.median(bf[sel]))
    return (beta_med * 299792458.0 / (2 * np.pi * f_med)) ** 2, beta_med


# 0) 真机纪律：确认当前无其他 openEMS 在跑（串行纪律；wmic 在新
# Windows 已移除，用 tasklist 过滤映像名）
probe = subprocess.run(
    ["tasklist", "/FI", "IMAGENAME eq openEMS.exe", "/FO", "CSV", "/NH"],
    capture_output=True, text=True)
others = [ln for ln in (probe.stdout or "").splitlines()
          if ln.strip().upper().startswith('"OPENEMS')]
if others:
    _fail(f"已有 openEMS 进程在跑（串行纪律）：{others}")

# 1) demo 板生成
build = build_demo_cpwg_pcb(PCB, w_mm=DEMO_W_MM, gap_mm=DEMO_GAP_MM)
if not build["success"]:
    _fail(f"demo 板生成失败: {build}")

# 2) 提取（stage-2：走线+zone+pad）
ext = extract_pcb(PCB)
if not ext["ok"]:
    _fail(f"提取失败: {ext['errors']}")
rf = [t for t in ext["traces"] if t["net"] == "RF1"]
if len(rf) != 1:
    _fail(f"RF1 主线应恰一条，得 {len(rf)}")
W = float(rf[0]["width_mm"])
L = float(rf[0]["length_mm"])
f_cu_gnd = [z for z in ext["zones"]
            if z["net"] == "GND" and z["layer"] == "F.Cu"]
if len(f_cu_gnd) != 1 or f_cu_gnd[0]["clearance_mm"] is None:
    _fail(f"F.Cu GND zone 应恰一个且带 clearance，得 {f_cu_gnd}")
GAP = float(f_cu_gnd[0]["clearance_mm"])
n_pads = sum(len(f["pads"]) for f in ext["footprints"])
print(f"提取: w={W}mm L={L}mm gap(zone)={GAP}mm pads={n_pads} "
      f"er={ext['board']['substrate_er']} "
      f"厚={ext['board']['thickness_mm']}mm")
if abs(GAP - DEMO_GAP_MM) > 1e-6:
    _fail(f"zone clearance {GAP} 偏离生成名义 {DEMO_GAP_MM}（往返锚破坏）")

# 3) 确定性代理寻优环（service，闭式内核）
opt = optimize_cpw_from_extract({"extract": ext})
if not opt["ok"]:
    _fail(f"寻优环失败: {opt['error']}")
print(f"寻优环: z0_extracted={opt['analysis']['z0_extracted_ohm']}Ω "
      f"eps_eff={opt['analysis']['eps_eff_extracted']} "
      f"w*={opt['optimization']['w_opt_mm']}mm "
      f"Δw={opt['optimization']['delta_w_mm']}mm "
      f"verdict={opt['verdict']}")

recipe = autotune_recipe_from_extract({"extract": ext},
                                      WORK / "b6_autotune_recipe.yaml")
if not recipe["ok"]:
    _fail(f"配方落盘失败: {recipe['error']}")

opt_verdict = "PASS" if (
    opt["verdict"] == "PASS"
    and abs(float(opt["optimization"]["w_opt_mm"]) - W) <= 0.02) else "FAIL"
print(f"KICAD_B6_S2_OPTIMIZER_{opt_verdict}（提取参数闭式判据："
      f"|z0−50|≤2Ω 且 |w*−w|≤0.02mm）")

# 4) openEMS 真板抽查（锚腿 mesh 0；gap 出自 zone 链路）
eps_ref, _z0_ref = _cpwg_ri(W, GAP, 0.508, 3.66)
print(f"CPWG 闭式参考: eps_ref={eps_ref:.4f}")
leg_dir = WORK / "openems_anchor"
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(leg_dir), freq_range_ghz=FREQ_RANGE,
    mesh_resolution_mm=0.0,
    extra_params={"solve_timeout_s": 36000}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "cpw", "params": {
    "w_mm": W, "gap_mm": GAP, "line_len_mm": L}})
t0 = time.time()
result = solver.solve()
print(f"  solve_s={time.time() - t0:.0f} success={result.success} "
      f"msg={result.message}")
if not result.success or result.s_params is None:
    _fail(f"openEMS 求解失败: {result.message}")
s11 = result.s_params[:, 0, 0]
m11_max = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
eps_engine, beta_med = _eps_from_beta(leg_dir / "port_beta.csv")
delta = (eps_engine / eps_ref - 1) * 100
print(f"锚腿 mesh0: eps_engine={eps_engine:.4f} delta={delta:+.2f}% "
      f"s11_max_db={m11_max:.1f}（stage-1 锚腿基线 2.5173/−1.95%/−22.5）")

em_verdict = "PASS" if (m11_max < -10 and abs(delta) <= 2.0) else "FAIL"
print(f"KICAD_B6_S2_EM_ANCHOR_{em_verdict}（zone 链路参数 openEMS 真跑："
      f"|S11|max<−10dB 且 |Δεeff|≤2% β 金标准口径）")

(WORK / "stage2_summary.json").write_text(json.dumps({
    "extract": {"w_mm": W, "line_len_mm": L, "gap_mm_from_zone": GAP,
                "n_pads": n_pads, "er": ext["board"]["substrate_er"]},
    "optimizer": {"z0_extracted_ohm": opt["analysis"]["z0_extracted_ohm"],
                  "w_opt_mm": opt["optimization"]["w_opt_mm"],
                  "delta_w_mm": opt["optimization"]["delta_w_mm"],
                  "verdict": opt_verdict},
    "em_anchor": {"eps_engine": eps_engine, "eps_ref": eps_ref,
                  "delta_pct": delta, "s11_max_db": m11_max,
                  "beta_med": beta_med, "verdict": em_verdict},
    "verdicts": {"optimizer": opt_verdict, "em_anchor": em_verdict},
}, ensure_ascii=False, indent=1), encoding="utf-8")
if "FAIL" in (opt_verdict, em_verdict):
    sys.exit(1)
print("KICAD_B6_S2_PASS")
