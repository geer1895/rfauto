"""2027 e2e final-2: strip example-specific python-load lines, rerun hpeesofsim, parse .ds."""
import glob
import os
import subprocess

ADS = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
env = os.environ.copy()
env["HPEESOF_DIR"] = ADS
env["PATH"] = ";".join([rf"{ADS}\bin", rf"{ADS}\adsptolemy\lib.win32_64",
                        rf"{ADS}\tools\python", env.get("PATH", "")])

workdir = r"D:/rf_workspace\scripts\spike_b_ads\sim_out_2027"
os.makedirs(workdir, exist_ok=True)

# 剥离示例特有的 python 模块加载与二级 ParamSweep（保留 SP1 主仿真）
src = open(r"D:/rf_workspace\scripts\spike_b_ads\sample_netlist_2027.txt", errors="ignore").read()
lines = src.splitlines()
kept, skip_blocks = [], 0
for line in lines:
    l = line.strip()
    if l.startswith("#load") or l.startswith("Component Module="):
        continue
    if l.startswith("ParamSweep:SweepX") or l.startswith("SweepPlan: SweepX_stim"):
        continue
    kept.append(line)
nl = os.path.join(workdir, "netlist.txt")
with open(nl, "w", encoding="ascii", errors="ignore") as f:
    f.write("\n".join(kept) + "\n")

with open(os.path.join(workdir, "sim_out.txt"), "w") as fo, open(os.path.join(workdir, "sim_err.txt"), "w") as fe:
    p = subprocess.run([rf"{ADS}\bin\hpeesofsim.exe",
                        "-I", rf"{ADS}\smart\simulation\amplifier\data",
                        "netlist.txt"],
                       cwd=workdir, env=env, stdout=fo, stderr=fe, timeout=600)
print("EXIT:", p.returncode)

out = open(os.path.join(workdir, "sim_out.txt"), errors="ignore").read()
rep = open(r"D:/rf_workspace\scripts\spike_b_ads\p27_sim_report.txt", "w", encoding="utf-8")
rep.write(out[-1200:])
rep.write("\n\nFILES:\n")
for f2 in glob.glob(workdir + "/**/*", recursive=True):
    rep.write(f2 + "\n")
rep.close()
print("report written")
