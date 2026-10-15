"""ADS 2027 end-to-end: open workspace -> generate_netlist -> hpeesofsim -> parse .ds.

Run with: <ADS>\\tools\\python\\python.exe（ADS = RFAUTO_HPEESOF_DIR，缺省 E:\\ADS\\ADS27） p27_2_e2e.py
"""
import os

ADS = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
os.environ["HPEESOF_DIR"] = ADS

import keysight.ads.de as de

wrk = r"D:\rf_workspace\scripts\spike_b_ads\sample_wrk27\Datalink_Basics_wrk"
if de.workspace_is_open():
    de.close_workspace()
ws = de.open_workspace(wrk)
print("open:", ws.is_open)

# 遍历 schematic，逐个尝试生成 netlist，记录成败与错误
out = open(r"D:\rf_workspace\scripts\spike_b_ads\p27_netlist_report.txt", "w", encoding="utf-8")
netlist_text = None
# 2027 API 漂移：library_names 是属性（set）而非方法
libs = ws.library_names if isinstance(ws.library_names, (set, list, tuple)) else ws.library_names()
for lib_name in libs:
    lib = ws.open_library(lib_name)
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            if not lcv.endswith(":schematic"):
                continue
            try:
                d = de.find_design_by_name(lcv, de.DesignMode.READ_ONLY)
                nl = d.generate_netlist()
                out.write(f"OK   {lcv}\n")
                if netlist_text is None:
                    netlist_text = str(nl)
            except Exception as e:
                out.write(f"FAIL {lcv}: {e}\n")
out.close()
print("netlist report written")

if netlist_text:
    nl_path = r"D:\rf_workspace\scripts\spike_b_ads\sample_netlist_2027.txt"
    with open(nl_path, "w", encoding="ascii", errors="ignore") as f:
        f.write(netlist_text)
    print("=== netlist head ===")
    print("\n".join(netlist_text.splitlines()[:40]))
