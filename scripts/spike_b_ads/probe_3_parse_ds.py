"""Spike B probe 3: parse an existing .ds dataset into a DataFrame.

Run with: E:\\ADS\\ads2023\\tools\\python\\python.exe probe_3_parse_ds.py
"""
import os

os.environ.setdefault("HPEESOF_DIR", r"E:\ADS\ads2023")

import keysight.ads.dataset as dataset

path = r"E:\ADS\ads2023\examples\Training\Conversion_Sample\WORKSHOP_prj\data\LPF_SCH.ds"
data = dataset.open(path)
print("opened:", path)
names = list(data.keys())
print("traces:", names[:10])

key = names[0]
df = data[key].to_dataframe().reset_index()
print("dataframe head:\n", df.head())
print("columns:", list(df.columns))
print("rows:", len(df))
