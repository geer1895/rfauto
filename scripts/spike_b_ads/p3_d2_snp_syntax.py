"""P3-D2: 实证 SnP 组件（外部 Touchstone 导入）的网表语法。

ground truth 来源: p3_d1_probe 从 ads_pelib:REMI_supply 取到的官方网表
    SnP:CEMI_CABLE  N__24 Reference Vin_p Vin_n NumPorts=4
    File=".pi_cemi/cispr25_cable.sio" Type="smatrixio" InterpMode="linear"
    InterpDom="" ExtrapMode="constant" Temp=27.0 CheckPassivity=0
未知点: 2/3 端口时的节点列表约定(是否含地) + Touchstone 的 Type 取值。
方法: 7 个候选变体各跑一次 hpeesofsim, 用求解器报错收敛到可用语法。

运行: <ADS>/tools/python/python.exe p3_d2_snp_syntax.py
"""
import json
import os
import shutil
import subprocess

ADS = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
os.environ["HPEESOF_DIR"] = ADS
env = os.environ.copy()
env["PATH"] = ";".join([os.path.join(ADS, "bin"),
                        os.path.join(ADS, "adsptolemy", "lib.win32_64"),
                        os.path.join(ADS, "tools", "python"),
                        env.get("PATH", "")])

SRC_S2P = rf"{ADS}\examples\DesignKit\DemoKit_MTM\circuit\data\demo_BP.s2p"
BASE = r"D:\rf_workspace\scripts\spike_b_ads\p3_d2_out"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)
shutil.copy2(SRC_S2P, os.path.join(BASE, "demo_BP.s2p"))

OPTS = "Options ResourceUsage=yes UseNutmegFormat=no EnableOptim=no"
PORTS = [
    "Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes",
    "Port:P2  P2 0 Num=2 Z=50 Ohm Noise=yes",
]
SP = [
    "S_Param:SP1 CalcS=yes CalcY=no CalcZ=no SweepVar=freq SweepPlan=SP1_stim "
    "    OutputPlan=SP1_Output StatusLevel=2",
    "SweepPlan: SP1_stim Start=1 GHz Stop=6 GHz Lin=31",
    "OutputPlan:SP1_Output Type=Output EquationNestLevel=2 SavedEquationNestLevel=2",
]

def mk(nodes, dtype, uselib=False, interpdom_ma=False):
    lines = [OPTS]
    if uselib:
        lines.append("#uselib ckt , SnP")
    lines.extend(PORTS)
    lines.extend(SP)
    snap = "SnP:SNP1  " + nodes + " File=demo_BP.s2p Type=" + dtype
    snap += " InterpMode=linear ExtrapMode=constant Temp=27.0 CheckPassivity=0"
    if interpdom_ma:
        snap += " InterpDom=ma"
    lines.append(snap)
    return "\n".join(lines) + "\n"

CASES = [
    ("v1_base_smatrixio", dict(nodes="P1 P2 NumPorts=2", dtype="smatrixio")),
    ("v2_uselib", dict(nodes="P1 P2 NumPorts=2", dtype="smatrixio", uselib=True)),
    ("v3_touchstone", dict(nodes="P1 P2 NumPorts=2", dtype="touchstone")),
    ("v4_type_snp", dict(nodes="P1 P2 NumPorts=2", dtype="snp")),
    ("v5_nodes_with_gnd", dict(nodes="P1 0 P2 0 NumPorts=2", dtype="smatrixio")),
    ("v6_interpdom_ma", dict(nodes="P1 P2 NumPorts=2", dtype="smatrixio", interpdom_ma=True)),
    ("v7_no_numports", dict(nodes="P1 P2", dtype="smatrixio")),
]

REPORT = os.path.join(BASE, "p3_d2_report.txt")
SUMMARY = os.path.join(BASE, "p3_d2_summary.json")
log = open(REPORT, "w", encoding="utf-8")
log.write("s2p: " + SRC_S2P + "\n")
log.write("s2p head: " + open(SRC_S2P, encoding="ascii", errors="ignore").readline().strip() + "\n")

rows = []
for name, kw in CASES:
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    nl = mk(**kw)
    with open(os.path.join(d, "netlist.txt"), "w", encoding="ascii", errors="ignore") as f:
        f.write(nl)
    args = [os.path.join(ADS, "bin", "hpeesofsim.exe"), "netlist.txt"]
    try:
        p = subprocess.run(args, cwd=d, env=env, capture_output=True, timeout=300)
        rc = p.returncode
        err = p.stderr.decode("ascii", errors="ignore")
        out = p.stdout.decode("ascii", errors="ignore")
    except Exception as exc:
        rc = -1
        err = str(exc)
        out = ""
    ds = [f for f in os.listdir(d) if f.endswith(".ds")]
    rows.append({"variant": name, "returncode": rc, "ds": ds,
                 "stderr_tail": err.strip()[-500:], "stdout_tail": out.strip()[-300:]})
    log.write("=" * 70 + "\n")
    log.write(name + "  rc=" + str(rc) + "  ds=" + str(ds) + "\n")
    log.write("--- netlist ---\n" + nl + "--- end netlist ---\n")
    log.write("--- stderr tail ---\n" + err.strip()[-1000:] + "\n")
    log.write("--- stdout tail ---\n" + out.strip()[-500:] + "\n")
    log.flush()

log.close()
with open(SUMMARY, "w", encoding="utf-8") as f:
    json.dump(rows, f, indent=2, ensure_ascii=False)

for r in rows:
    tag = "OK   " if r["ds"] else "FAIL"
    print(tag + " " + r["variant"] + " rc=" + str(r["returncode"]) + " ds=" + str(r["ds"]))
print("report:", REPORT)
