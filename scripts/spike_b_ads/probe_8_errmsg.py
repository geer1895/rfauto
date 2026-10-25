"""Spike B probe 8: capture full netlist error messages."""
import os

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")
import keysight.ads.de as de

wrk_dir = r"D:/rf_workspace\scripts\spike_b_ads\sample_wrk\Datalink_Basics_wrk"
if de.workspace_is_open():
    de.close_workspace()
ws = de.open_workspace(wrk_dir)

out = open(r"D:/rf_workspace\scripts\spike_b_ads\probe8_out.txt", "w", encoding="utf-8")
for lib_name in ws.library_names():
    lib = ws.open_library(lib_name)
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            if not lcv.endswith(":schematic"):
                continue
            try:
                d = de.find_design_by_name(lcv, de.DesignMode.READ_ONLY)
                nl = d.generate_netlist()
                out.write(f"OK {lcv}: {str(nl)[:300]}\n")
            except Exception as e:
                out.write(f"FAIL {lcv}: {e}\n")
out.write("\nmodule-level generate_netlist doc:\n")
out.write(str(getattr(de.generate_netlist, "__doc__", "")))
out.close()
print("written")
