"""Dump keysight.ads.de public API on 2027 + find design-access entry points."""
import os

os.environ["HPEESOF_DIR"] = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
import keysight.ads.de as de

lines = [f"{a} ({type(getattr(de, a)).__name__})" for a in dir(de) if not a.startswith("_")]
with open(r"D:/rf_workspace\scripts\spike_b_ads\de_api_2027.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

# 设计访问相关
hits = [a for a in lines if any(k in a.lower() for k in ("design", "netlist", "cell", "simulate"))]
with open(r"D:/rf_workspace\scripts\spike_b_ads\p27_api_hits.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(hits))
print("total:", len(lines), "hits:", len(hits))
