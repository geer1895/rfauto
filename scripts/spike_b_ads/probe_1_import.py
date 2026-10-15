"""Spike B probe 1: import keysight.ads from ADS bundled Python (external process).

Run with: E:\\ADS\\ads2023\\tools\\python\\python.exe probe_1_import.py
"""
import os
import sys

print("python:", sys.version)
os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")

try:
    import keysight.ads
    print("keysight.ads OK:", keysight.ads)
    import keysight.ads.de as de
    print("de attrs:", [a for a in dir(de) if not a.startswith("_")][:20])
    import keysight.ads.dds as dds
    print("dds OK:", dds)
except Exception as e:
    print("IMPORT FAIL:", type(e).__name__, e)
