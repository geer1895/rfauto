# 实测相关性基线（E9c / ADR-0018 双基线）

本目录存放"仿真 vs 实测"相关性分析的实测基线文件，供
`rfauto correlate` / MCP `correlate_measurement` 作为长期参照。

## 约定

- 每个基线一个子目录：`<model>_<author>_<date>/`
  - `measured.sNp`：实测 Touchstone（VNA 原始导出，不得修改）
  - `baseline.yaml`：基线元数据（见下 schema）
- 相关性判定用双基线（ADR-0018）：**绝对基线**（本目录实测文件）
  + **相对基线**（同配方两次仿真的自一致阈值）。任一超差即告警。

## baseline.yaml schema

```yaml
model: wilkinson_power_divider   # rfauto 模型名
vna: "Keysight E5061B"           # 测量仪器
cal: "SOLT"                      # 校准方式
measured_file: measured.s2p
freq_range_ghz: [2.3, 2.5]
threshold_db: 3.0                # 相关性阈值
notes: "..."
recorded_by: "<人名>"
date: "2026-09-01"
```

## 当前状态

暂无实测基线——需要首次真机 VNA 实测后按上述约定归档。
验收口径（E9c）：`rfauto correlate <sim.s2p> knowledge/correlation/<基线>/measured.s2p`
能出 is_correlated 判定即闭环。
