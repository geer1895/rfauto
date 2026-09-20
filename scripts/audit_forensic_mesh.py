"""取证：为什么 wilkinson 模板的所有金属原语 Unused？

变体矩阵（只建算子跑 10 步，秒级）：
  V0 基线（现模板口径）
  V1 无 SmoothMeshLines
  V2 AddEdges2Grid dirs="xy"（官方平版金属口径，z 不加边）
  V3 V2 + SmoothMesh
另 dump 网格 z 轴线与 XML 前若干 KB。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "runs" / "audit_forensic"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

TEMPLATE = (ROOT / "src" / "rfauto" / "adapters" / "openems_templates.py").read_text(encoding="utf-8")

# 从模板里抽出公共头部（去 f-string 已渲染）——直接重新渲染
sys.path.insert(0, str(ROOT))
from rfauto.adapters.openems_templates import render_script  # noqa: E402

base_script = render_script(
    "wilkinson", {"series_w_mm": 1.113, "shunt_w_mm": 0.604, "arm_len_mm": 18.1},
    (1.5, 3.5), mesh_resolution_mm=0.5)

VARIANTS = {
    "V0_baseline": base_script,
    "V1_no_smooth": base_script.replace(
        'mesh.SmoothMeshLines("all", BASE, 1.4)', "# smooth disabled"),
    "V2_edges_xy": base_script.replace(
        'FDTD.AddEdges2Grid(dirs="xyz", metal_edge_res=MESH)',
        'FDTD.AddEdges2Grid(dirs="xy", metal_edge_res=MESH)'),
    "V3_xy_smooth": base_script.replace(
        'FDTD.AddEdges2Grid(dirs="xyz", metal_edge_res=MESH)',
        'FDTD.AddEdges2Grid(dirs="xy", metal_edge_res=MESH)'),
}
# V3 = edges_xy 且无 smooth
VARIANTS["V3_xy_nosmooth"] = VARIANTS["V2_edges_xy"].replace(
    'mesh.SmoothMeshLines("all", BASE, 1.4)', "# smooth disabled")

results = []
for name, script in VARIANTS.items():
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    # 只建算子跑 10 步
    small = script.replace("NrTS=60000", "NrTS=10")
    (d / "simulation.py").write_text(small, encoding="utf-8")
    r = subprocess.run([PY, "simulation.py"], cwd=d, capture_output=True,
                       text=True, timeout=600)
    warns = re.findall(r"Unused primitive.*", r.stderr + r.stdout)
    grid_info = ""
    m = re.search(r"FDTD simulation size: ([^\n]+)", r.stdout)
    if m:
        grid_info = m.group(1).strip()
    results.append(f"{name}: rc={r.returncode} unused={len(warns)} | {grid_info}")
    if warns:
        results.append("   " + warns[0])

# 网格 dump（V0 的 z 线，检查 0 / -H_SUB 是否在）
m = re.search(r'mesh\.AddLine\("z", np\.linspace\(-H_SUB, 0, 5\)\)', base_script)
results.append("template has substrate z-lines: " + str(bool(m)))

with open(WORK / "_tmp_forensic.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(results))
print("FORENSIC_DONE")
