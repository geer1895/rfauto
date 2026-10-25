"""2027 e2e final: hpeesofsim on generated netlist -> parse .ds -> DataFrame."""
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
nl = os.path.join(workdir, "netlist.txt")
import shutil

shutil.copy(r"D:/rf_workspace\scripts\spike_b_ads\sample_netlist_2027.txt", nl)

with open(os.path.join(workdir, "sim_out.txt"), "w") as fo, open(os.path.join(workdir, "sim_err.txt"), "w") as fe:
    p = subprocess.run([rf"{ADS}\bin\hpeesofsim.exe", "netlist.txt"],
                       cwd=workdir, env=env, stdout=fo, stderr=fe, timeout=600)
print("EXIT:", p.returncode)

out = open(os.path.join(workdir, "sim_out.txt"), errors="ignore").read()
tail = out[-1500:]
with open(r"D:/rf_workspace\scripts\spike_b_ads\p27_sim_report.txt", "w", encoding="utf-8") as f:
    f.write(tail)
    f.write("\n\nFILES:\n")
    for f2 in glob.glob(workdir + "/**/*", recursive=True):
        f.write(f2 + "\n")
print("report written")
