"""Spike B probe 6 (end-to-end): create workspace + schematic via Python API,
generate netlist, run hpeesofsim, parse .ds — all headless.

Run with: E:\\ADS\\ads2023\\tools\\python\\python.exe probe_6_end2end.py
"""
import os
import shutil

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")

import keysight.ads.de as de

ADS = r"E:\ADS\ads2023"
wrk_dir = r"D:\rf_workspace\scripts\spike_b_ads\auto_wrk"

if de.workspace_is_open():
    de.close_workspace()
if os.path.exists(wrk_dir):
    shutil.rmtree(wrk_dir)

ws = de.create_workspace(wrk_dir)
print("workspace created:", de.workspace_is_open())
print("ws type:", type(ws))
print("ws attrs:", [a for a in dir(ws) if not a.startswith("_")][:30])
