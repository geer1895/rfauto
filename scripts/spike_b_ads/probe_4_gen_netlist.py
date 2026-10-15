"""Spike B probe 4: open workspace via keysight.ads.de, generate netlist, run hpeesofsim.

Run with: E:\\ADS\\ads2023\\tools\\python\\python.exe probe_4_gen_netlist.py
"""
import os

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")

import keysight.ads.de as de

wrk = r"D:\rf_workspace\scripts\spike_b_ads\sample_wrk\Datalink_Basics_wrk"
de.open_workspace(wrk)
print("workspace open:", de.workspace_is_open())

lib_names = de.workspace.library_names()
print("libraries:", list(lib_names))

# 找一个 schematic cell
target = None
for lib_name in lib_names:
    lib = de.workspace.open_library(lib_name)
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            print("  view:", lcv)
            if target is None and lcv.endswith(":schematic"):
                target = lcv

if target is None:
    print("NO schematic found in this workspace")
else:
    design = de.find_design_by_name(target, de.DesignMode.READ_ONLY)
    netlist = design.generate_netlist()
    print("=== NETLIST (first 60 lines) ===")
    lines = str(netlist).splitlines()
    print("\n".join(lines[:60]))
    out = r"D:\rf_workspace\scripts\spike_b_ads\sample_netlist.txt"
    with open(out, "w", encoding="ascii", errors="ignore") as f:
        f.write(str(netlist))
    print("saved to", out)
