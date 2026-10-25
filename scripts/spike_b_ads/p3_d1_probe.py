r"""P3-D1 Spike: 取证 ADS 网表中「外部 S 参数数据导入」的真实组件语法。

现有 wilkinson_snp.net 用的是 P0 虚构语法 (S: SNP1 DBUF= / Term _1=SNP1.1)，
与 sample_netlist_2027.txt ground truth 不符；且 swept_s_parameter 示例网表
不含任何 S 参数数据导入组件。方法：ADS 2027 headless generate_netlist 全库扫描，
抓含 S 参数数据导入标记的网表并落盘。

运行: <ADS>\tools\python\python.exe p3_d1_probe.py
"""
import json
import os
import re
import time

ADS = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
os.environ["HPEESOF_DIR"] = ADS

import keysight.ads.de as de
from keysight.ads.de._pde.db import DesignMode

BASE = r"D:/rf_workspace\scripts\spike_b_ads"
WRK = BASE + r"\sample_wrk27\Datalink_Basics_wrk"
OUT = BASE + r"\p3_d1_out"
SEP = os.sep
os.makedirs(OUT, exist_ok=True)

NLMARKERS = re.compile(
    r"(?i)(\bSNP\b|\bSNPFile\b|\bSnpFile\b|\bSP[2-9]P\b|"
    r"\.s[1234]p\b|\.xnp\b|\.snp\b)"
)

MAX_S = 1500.0
t0 = time.time()
if de.workspace_is_open():
    de.close_workspace()
ws = de.open_workspace(WRK)

libs = ws.library_names if isinstance(ws.library_names, (set, list, tuple)) else ws.library_names()
log = open(OUT + r"\p3_d1_report.txt", "w", encoding="utf-8")
log.write("workspace: " + WRK + "\nads version: " + str(de.version()) + "\n")

hits = []
scanned = 0
errors = 0
libs_seen = 0
limit_hit = False

for lib_name in libs:
    libs_seen += 1
    if time.time() - t0 > MAX_S:
        limit_hit = True
        break
    try:
        lib = ws.open_library(lib_name)
    except Exception as exc:
        errors += 1
        log.write("FAIL open_library " + str(lib_name) + ": " + str(exc) + "\n")
        continue
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            if not lcv.endswith(":schematic"):
                continue
            if time.time() - t0 > MAX_S:
                limit_hit = True
                break
            scanned += 1
            try:
                d = ws.design(lcv, DesignMode.READ_ONLY)
                nl = str(d.generate_netlist())
            except Exception as exc:
                errors += 1
                if errors <= 40:
                    log.write("FAIL netlist " + lcv + ": " + type(exc).__name__ + ": " + str(exc) + "\n")
                continue
            m = NLMARKERS.search(nl)
            if m:
                hits.append({"lcv": lcv, "marker": m.group(1), "n_lines": nl.count(chr(10))})
                safe = lcv.replace(":", "_").replace(SEP, "_")
                fpath = os.path.join(OUT, safe + ".txt")
                with open(fpath, "w", encoding="ascii", errors="ignore") as f:
                    f.write(nl)
                log.write("HIT  " + m.group(1).ljust(14) + "  " + lcv + "\n")
                log.flush()

log.write("\n=== scanned=%d libs=%d errors=%d hits=%d elapsed=%.0f limit=%s ===\n" % (scanned, libs_seen, errors, len(hits), time.time() - t0, limit_hit))
log.close()

summary = {"scanned": scanned, "libs": libs_seen, "errors": errors, "hits": len(hits),
           "elapsed_s": round(time.time() - t0, 1), "limit_hit": limit_hit, "hit_list": hits}
with open(os.path.join(OUT, "p3_d1_summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(json.dumps({"scanned": scanned, "errors": errors, "hits": len(hits),
                  "elapsed_s": round(time.time() - t0, 1), "limit_hit": limit_hit}))
for h in hits[:30]:
    print("  HIT " + h["marker"].ljust(10) + " " + h["lcv"])
print("report:", os.path.join(OUT, "p3_d1_report.txt"))
