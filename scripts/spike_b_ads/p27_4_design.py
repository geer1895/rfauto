"""2027: locate DesignMode enum + generate netlist."""
import os

os.environ["HPEESOF_DIR"] = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
import keysight.ads.de as de

wrk = r"D:/rf_workspace\scripts\spike_b_ads\sample_wrk27\Datalink_Basics_wrk"
if de.workspace_is_open():
    de.close_workspace()
ws = de.open_workspace(wrk)

out = open(r"D:/rf_workspace\scripts\spike_b_ads\p27_design_report.txt", "w", encoding="utf-8")

# DesignMode 位置探测
candidates = []
try:
    from keysight.ads.de._pde.db import DesignMode
    candidates.append(("keysight.ads.de._pde.db.DesignMode", DesignMode))
except Exception as e:
    out.write(f"_pde.db import fail: {e}\n")
try:
    from keysight.ads.de.db import DesignMode
    candidates.append(("keysight.ads.de.db.DesignMode", DesignMode))
except Exception as e:
    out.write(f"de.db import fail: {e}\n")

lcv = "Datalink_Basics_lib:swept_s_parameter:schematic"
done = False
for name, DM in candidates:
    try:
        out.write(f"{name} members: {[m for m in dir(DM) if not m.startswith('_')]}\n")
        d = ws.design(lcv, DM.READ_ONLY)
        out.write(f"ws.design OK via {name}\n")
        nl = d.generate_netlist()
        out.write("NETLIST OK\n" + str(nl)[:2000] + "\n")
        with open(r"D:/rf_workspace\scripts\spike_b_ads\sample_netlist_2027.txt", "w", encoding="ascii", errors="ignore") as f:
            f.write(str(nl))
        done = True
        break
    except Exception as e:
        out.write(f"FAIL via {name}: {type(e).__name__}: {e}\n")
out.close()
print("done" if done else "failed")
