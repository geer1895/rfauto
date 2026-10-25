"""2027 e2e final: parse the simulated .ds -> DataFrame -> S-param sanity."""
import os

os.environ["HPEESOF_DIR"] = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")
import keysight.ads.dataset as dataset

path = r"D:/rf_workspace\scripts\spike_b_ads\sim_out_2027\swept_s_parameter.ds"
data = dataset.open(path)
print("traces:", list(data.keys()))
df = data[list(data.keys())[0]].to_dataframe().reset_index()
out = open(r"D:/rf_workspace\scripts\spike_b_ads\p27_parse_report.txt", "w", encoding="utf-8")
out.write(f"columns: {list(df.columns)}\nrows: {len(df)}\n")
out.write(df.head(3).to_string())
# S 参数量级 sanity
import numpy as np

s11 = df["S[1,1]"] if "S[1,1]" in df.columns else None
if s11 is not None:
    mag = np.abs(s11)
    out.write(f"\n|S11| range: {mag.min():.3f} ~ {mag.max():.3f}\n")
out.close()
print("report written")
