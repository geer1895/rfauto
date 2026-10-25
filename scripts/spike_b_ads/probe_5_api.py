"""List keysight.ads.de public API + workspace-related callables."""
import os

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")
import keysight.ads.de as de

out = []
for a in dir(de):
    if a.startswith("_"):
        continue
    obj = getattr(de, a)
    kind = type(obj).__name__
    out.append(f"{a} ({kind})")
with open(r"D:/rf_workspace\scripts\spike_b_ads\de_api.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("written", len(out), "attrs")
