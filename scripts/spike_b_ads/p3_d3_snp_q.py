"""P3-D3: SnP 语法第二轮 - 全部参数加引号(对齐 REMI ground truth) + 抓完整日志。

第一轮结论: v1 (SnP:SNP1  P1 P2 NumPorts=2 File=demo_BP.s2p Type=smatrixio) 网表
通过解析并进入仿真阶段, 说明节点约定"恰好 NumPorts 个节点名、不含地"是对的;
#uselib 需要引号 (#uselib ckt , SnP 报 unexpected IDENT, expecting STRING_CONSTANT)。

运行: <ADS>/tools/python/python.exe p3_d3_snp_q.py
"""
import json
import os
import re
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
BASE = r"D:/rf_workspace\scripts\spike_b_ads\p3_d3_out"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)
shutil.copy2(SRC_S2P, os.path.join(BASE, "demo_BP.s2p"))

OPTS = "Options ResourceUsage=yes UseNutmegFormat=no EnableOptim=no"
PORTS = [
    "Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes",
    "Port:P2  P2 0 Num=2 Z=50 Ohm Noise=yes",
]
SP = [
    'S_Param:SP1 CalcS=yes CalcY=no CalcZ=no SweepVar="freq" ',
    '    SweepPlan="SP1_stim" OutputPlan="SP1_Output" StatusLevel=2',
    "SweepPlan: SP1_stim Start=1 GHz Stop=6 GHz Lin=31",
    'OutputPlan:SP1_Output Type="Output" EquationNestLevel=2 ',
    '    SavedEquationNestLevel=2',
]

def mk(nodes, dtype, uselib=False, no_ports=False):
    lines = [OPTS]
    if uselib:
        lines.append('#uselib "ckt" , "SnP"')
    if not no_ports:
        lines.extend(PORTS)
    lines.extend(SP)
    snap = "SnP:SNP1  " + nodes + " "
    if dtype is None:
        snap += 'File="demo_BP.s2p" '
    else:
        snap += 'File="demo_BP.s2p" Type="'
        snap += dtype
        snap += '" '
    snap += 'InterpMode="linear" ExtrapMode="constant" '
    snap += 'Temp=27.0 CheckPassivity=0'
    lines.append(snap)
    return "\n".join(lines) + "\n"

CASES = [
    ("w1_smatrixio", dict(nodes="P1 P2 NumPorts=2", dtype="smatrixio")),
    ("w2_uselib", dict(nodes="P1 P2 NumPorts=2", dtype="smatrixio", uselib=True)),
    ("w3_touchstone", dict(nodes="P1 P2 NumPorts=2", dtype="touchstone")),
    ("w4_no_type", dict(nodes="P1 P2 NumPorts=2", dtype=None)),
    ("w5_type_snp", dict(nodes="P1 P2 NumPorts=2", dtype="snp")),
    ("w6_sourceless", dict(nodes="P1 P2 NumPorts=2", dtype="smatrixio", no_ports=True)),
]

SUMMARY = os.path.join(BASE, "p3_d3_summary.json")
rows = []
for name, kw in CASES:
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    nl = mk(**kw)
    with open(os.path.join(d, "netlist.txt"), "w", encoding="ascii", errors="ignore") as f:
        f.write(nl)
    args = [os.path.join(ADS, "bin", "hpeesofsim.exe"), "netlist.txt"]
    rc = -1
    out = ""
    err = ""
    try:
        p = subprocess.run(args, cwd=d, env=env, capture_output=True, timeout=300)
        rc = p.returncode
        out = p.stdout.decode("ascii", errors="ignore")
        err = p.stderr.decode("ascii", errors="ignore")
    except Exception as exc:
        err = str(exc)
    full = out + "\n[stderr] " + err
    errs = []
    for l in full.splitlines():
        if re.search(r"(?i)error|terminated due|not found|fail", l):
            errs.append(l.strip())
    ds = [f for f in os.listdir(d) if f.endswith(".ds")]
    rows.append({"variant": name, "rc": rc, "ds": ds, "errors": errs[:15],
                 "netlist": nl.splitlines()[-1]})

with open(SUMMARY, "w", encoding="utf-8") as f:
    json.dump(rows, f, indent=2, ensure_ascii=False)

for r in rows:
    tag = "OK   " if r["ds"] else "FAIL"
    print(tag + " " + r["variant"] + " rc=" + str(r["rc"]) + " ds=" + str(r["ds"]))
    for e in r["errors"][:6]:
        print("       " + e[:160])
print("summary:", SUMMARY)
