# Spike B — ADS 通道探测（P1 末，2026-08-29）

用 ADS 自带 Python（`E:\ADS\ads2023\tools\python\python.exe`，3.10.8）运行。
结论与决策见 `docs/adr/ADR-0008-ADS联动主通道采用PythonAPI网表通道为备.md`。

## 脚本清单（按执行顺序）

| 脚本 | 探测内容 | 结果 |
|------|----------|------|
| probe_1_import.py | 外部进程导入 keysight.ads.de | ✅ 可导入（打印 Design Environment banner） |
| probe_2_dataset.py | 数据集模块名探测 | ✅ `keysight.ads.dataset`（非文档中的 dds） |
| probe_3_parse_ds.py | .ds → DataFrame | ✅ LPF_SCH.ds 解析出 S 参数 + PortZ（91×7） |
| probe_4_gen_netlist.py | 首次 netlist 生成（API 版本差异） | ⚠ `de.workspace` → 应为 `active_workspace()` |
| probe_5_api.py | dump keysight.ads.de 全部公开 API → de_api.txt | ✅ 127 attrs；有 create_workspace/ael bridge |
| probe_6_end2end.py | 纯代码 create_workspace | ✅ 可建（目录须不存在）；is_open 是属性 |
| probe_7_design.py | 打开示例工作区遍历 schematic 生成 netlist | ❌ 全部 `no item definition`（headless 标准库未加载） |
| probe_8_errmsg.py | 逐 cell 捕获完整错误信息 | ❌ 同上，确认为 P3 待解问题 |

其他产物：
- `sample_wrk/Datalink_Basics_wrk/` — 从 `examples\Basics\Datalink_Basics_wrk.7zads` 解压（ADS bin 自带 7z.exe）
- `hpeesofsim` 直跑 netlist 的要点：PATH 需加 `adsptolemy\lib.win32_64` + `tools\python`；netlist 文件必须无 BOM；SP 分析控件语法待 ground-truth 网表确认
- `run_sim.py` / `try_variants.py` — hpeesofsim 批处理驱动与语法变体尝试

## P3 交接

1. headless `generate_netlist` 的库加载问题（候选：`de.ael` AEL bridge 预载 / GUI 生成 netlist 模板注入）
2. SP 分析控件 netlist 语法（同上，拿到一份 GUI 生成的网表即可）
3. `keysight.edatoolbox`（官方 EDA Toolbox，示例中的 CircuitSimulator 封装）可选安装
