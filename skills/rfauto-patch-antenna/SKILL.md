---
name: rfauto-patch-antenna
description: 用 rfauto 调优 patch_antenna（2 个可调参数，带内目标 1 项）
version: 1
---

# rfauto skill：patch_antenna

## 器件与目标

- 模型插件：`patch_antenna`；扫频 1.5–3.5 GHz。
- 带内目标（objectives）：
  - `s11_db` max_below -10 @ [2.3, 2.5] GHz

## 可调参数（optimization.params）

| 参数 | low | high |
|---|---|---|
| patch_len_mm | 35.0 | 45.0 |
| feed_offset_mm | 5.0 | 15.0 |

## 标准工作流（typed 命令，数值由确定性内核产出）

```bash
rfauto validate patch_antenna_v1.yaml          # 配方校验
rfauto run patch_antenna_v1.yaml -a fake       # fake 快验证（秒级）
rfauto autotune patch_antenna_v1.yaml --budget 3   # 确定性 critique 自治环
rfauto tune patch_antenna_v1.yaml -a openems --max-trials 30  # 外环寻优
rfauto calibrate patch_antenna_v1.yaml --sampler openems  # 代理校准（如接入）
rfauto p0 <recipe> --high-adapter hfss   # 终验（商业求解器收口）
```

## 扫描 notebook 骨架（openEMS 快验证）

```python
from rfauto.adapters.em_solver_base import EMSolverConfig
from rfauto.adapters.openems_solver import OpenEMSSolver

solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems",
    freq_range_ghz=tuple([1.5, 3.5]),
    mesh_resolution_mm=0.45,  # 网格 base 覆盖；0=自动 λ_sub/50
))
solver.connect()
solver.build_geometry({"template": None, "params": {}})  # 填参数点
result = solver.solve()
```

## 边界（硬约束）

- LLM/agent 不产生物理数字：所有指标来自求解器与确定性评判器。
- 对配方的任何修改走沙箱草稿 → 三层 Gate 审批（agent 写面隔离）。
- FAIL 如实记录，不凑绿。
