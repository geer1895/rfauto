"""Spike B probe 7 (end-to-end): open sample workspace -> generate_netlist ->
hpeesofsim -> parse .ds, all headless via Python API.

Run with: E:\\ADS\\ads2023\\tools\\python\\python.exe probe_7_design.py
"""
import os

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")

import keysight.ads.de as de

ADS = r"E:\ADS\ads2023"
wrk_dir = r"D:\rf_workspace\scripts\spike_b_ads\sample_wrk\Datalink_Basics_wrk"

if de.workspace_is_open():
    de.close_workspace()
ws = de.open_workspace(wrk_dir)
print("open:", ws.is_open)

# 找 schematic
target = None
for lib_name in ws.library_names():
    lib = ws.open_library(lib_name)
    print("lib:", lib_name)
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            print("  view:", lcv)
            if target is None and lcv.endswith(":schematic"):
                target = lcv

if not target:
    print("NO schematic view in this workspace")
    raise SystemExit(0)

print("TARGET:", target)

# 遍历 schematic，找到第一个能成功生成 netlist 的（部分 cell 含纯展示组件不可 netlist）
nl_path = r"D:\rf_workspace\scripts\spike_b_ads\sample_netlist.txt"
done = False
schematics = []
for lib_name in ws.library_names():
    lib = ws.open_library(lib_name)
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            if lcv.endswith(":schematic"):
                schematics.append(lcv)

for lcv in schematics:
    try:
        d = de.find_design_by_name(lcv, de.DesignMode.READ_ONLY)
        netlist = d.generate_netlist()
    except Exception as e:
        print(f"  skip {lcv}: {type(e).__name__}")
        continue
    text = str(netlist)
    print(f"=== netlist of {lcv} (head) ===")
    print("\n".join(text.splitlines()[:60]))
    with open(nl_path, "w", encoding="ascii", errors="ignore") as f:
        f.write(text)
    print("saved:", nl_path)
    done = True
    break

if not done:
    print("NO netlistable schematic found")
raise SystemExit(0 if done else 1)
