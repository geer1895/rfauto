"""Spike B-2 probe 1 (ADS 2027): import keysight.ads.de/dataset + version info.

Run with: <ADS>\\tools\\python\\python.exe（ADS = RFAUTO_HPEESOF_DIR，缺省 E:\\ADS\\ADS27） p27_1_import.py
"""
import os
import sys

os.environ["HPEESOF_DIR"] = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")

print("python:", sys.version)
import keysight.ads.de as de

print("de OK, version:", de.version() if callable(getattr(de, "version", None)) else "?")
print("running_automation:", de.running_automation() if callable(getattr(de, "running_automation", None)) else "?")

try:
    import keysight.ads.dataset as dataset
    print("dataset OK")
except ImportError as e:
    print("dataset FAIL:", e)

# 新增模块探测（2027 宣传的 MCP/macro/PyPDK 相关）
import pkgutil

import keysight

print("keysight submodules:", sorted(m.name for m in pkgutil.iter_modules(keysight.__path__)))
for sub in ("keysight.ads.simulation", "keysight.ads.mcp", "keysight.ads.pypdk", "keysight.edatoolbox"):
    try:
        __import__(sub)
        print("OK:", sub)
    except Exception as e:
        print("no:", sub, "->", type(e).__name__)
