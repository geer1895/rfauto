"""Spike B probe 2: dataset module + existing .ds parsing.

Run with: E:\\ADS\\ads2023\\tools\\python\\python.exe probe_2_dataset.py <path.ds>
"""
import os
import sys

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")

print("de module OK")

# 找数据集模块
dds = None
for name in ("keysight.ads.dataset", "keysight.ads.dds", "keysight.ads.data"):
    try:
        dds = __import__(name, fromlist=["x"])
        print("dataset module:", name)
        break
    except ImportError as e:
        print("no", name, "->", e)

if dds is None:
    import pkgutil

    import keysight
    print("keysight submodules:", [m.name for m in pkgutil.iter_modules(keysight.__path__)])
    sys.exit(0)

# 若给了 .ds 文件则解析
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    path = sys.argv[1]
    data = dds.open(path)
    print("opened:", path)
    try:
        print("traces:", list(data.keys())[:10] if hasattr(data, "keys") else dir(data)[:20])
    except Exception as e:
        print("keys exc:", e)
else:
    print("no .ds given")
