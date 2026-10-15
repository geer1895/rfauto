"""P3-D5: 3 port SnP test."""
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

BASE = r"D:\rf_workspace\scripts\spike_b_ads\p3_d5_out"
SRC = os.path.join(BASE, "wilkinson_like.s3p")
d = os.path.join(BASE, "run3p")
shutil.rmtree(d, ignore_errors=True)
os.makedirs(d, exist_ok=True)
shutil.copy2(SRC, os.path.join(d, "wilkinson_like.s3p"))

lines = [
    "Options ResourceUsage=yes UseNutmegFormat=no EnableOptim=no",
    'S_Param:SP1 CalcS=yes CalcY=no CalcZ=no StatusLevel=2 SweepVar="freq" SweepPlan="SP1_stim" OutputPlan="SP1_Output"',
    "SweepPlan: SP1_stim Start=1.5 GHz Stop=3.5 GHz Lin=41",
    'OutputPlan:SP1_Output Type="Output" EquationNestLevel=2 SavedEquationNestLevel=2',
    'Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes',
    'Port:P2  P2 0 Num=2 Z=50 Ohm Noise=yes',
    'Port:P3  P3 0 Num=3 Z=50 Ohm Noise=yes',
    'SnP:SNP1  P1 P2 P3 NumPorts=3 File="wilkinson_like.s3p" Type="touchstone" InterpMode="linear" InterpDom="" ExtrapMode="constant" Temp=27.0 CheckPassivity=0',
]
nl = "\n".join(lines) + "\n"
with open(os.path.join(d, "netlist.txt"), "w", encoding="ascii", errors="ignore") as f:
    f.write(nl)

p = subprocess.run([os.path.join(ADS, "bin", "hpeesofsim.exe"), "netlist.txt"],
                   cwd=d, env=env, capture_output=True, timeout=300)
out = p.stdout.decode("ascii", errors="ignore")
err = p.stderr.decode("ascii", errors="ignore")
ds_files = [f for f in os.listdir(d) if f.endswith(".ds")]
print("rc=%d ds=%s" % (p.returncode, ds_files))
for l in (out + "\n" + err).splitlines():
    low = l.lower()
    if "error" in low or "terminated" in low:
        print("  ERR:", l.strip()[:200])

if ds_files:
    import keysight.ads.dataset as ksds
    import numpy as np
    data = ksds.open(os.path.join(d, ds_files[0]))
    print("ds keys:", list(data.keys()))
    df = data["SP1.SP"].to_dataframe().reset_index()
    print("shape:", df.shape)
    print("cols:", list(df.columns))
    print("freq_span: %.3f - %.3f GHz npts=%d" % (df["freq"].min()/1e9, df["freq"].max()/1e9, len(df)))
    m = int((df["freq"] - 2.4e9).abs().argmin())
    r = df.iloc[m]
    print("at f=%.3f GHz" % (r["freq"]/1e9))
    for i in (1, 2, 3):
        for j in (1, 2, 3):
            v = complex(r["S[%d,%d]" % (i, j)])
            print("  S[%d,%d] = %7.3f dB  %8.3f deg" % (i, j, 20*np.log10(abs(v)), np.degrees(np.angle(v))))
    print("PortName:", [r["PortName[%d]" % i] for i in (1, 2, 3)])
    print("PortZ:", [complex(r["PortZ[%d]" % i]) for i in (1, 2, 3)])
else:
    print("NO DATASET")
