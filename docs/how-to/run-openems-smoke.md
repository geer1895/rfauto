# 如何跑一次 openEMS 冒烟

**场景**：对 `docs/templates/<模板>/meta.yaml` 里的一个模板，先用最小
代价确认"几何画对了、端口激励起来了"，再谈精算。本文路径 =
**先离线审计（秒级零仿真）→ 真跑一个点 → 按判据判读**。

## 0. 环境自检

```python
import sys; sys.path.insert(0, "src")
from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.em_solver_base import EMSolverConfig

print(resolve_openems_exe())   # 解析顺序：configs/solvers.yaml →
                               # RFAUTO_OPENEMS_BIN → 兜底字面量
assert OpenEMSSolver(EMSolverConfig(solver_type="openems",
    exe_path=resolve_openems_exe())).connect()
```

openEMS/CSXCAD 绑定缺失时先读 docs/openems_build_guide.md（源码编译，
无 PyPI wheel）。

## 1. 真跑之前：离线几何审计（必过）

**不经仿真、秒级**：渲染脚本 → exec 到 `FDTD.Run(` 为止 → 在 CSXCAD
实测对象上核对（原语非零体积、端口激励体积非零、导体连通性、网格最小
间距）。字符串存在性检查抓不住画法错误（历史上"中心线弦"馈电、共线
断口直通线都通过了 compile），判据必须落在 CSXCAD 实测对象上：

```python
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

text = render_script("mline", dict(TEMPLATE_NOMINAL["mline"]),
                     (2.15, 2.65), mesh_resolution_mm=0.4)
head = text[:text.index("FDTD.Run(")]      # 截掉求解段，只留建模
scope = {"__name__": "__main__", "__file__": "offline_audit.py"}
exec(compile(head, "offline_audit", "exec"), scope)
prims = scope["CSX"].GetAllPrimitives()
print("primitives:", len(prims))           # 实测原语数/类型/坐标进网格
```

本机实测：15 个 CSPrimBox，rc=0。全套判据的权威实现是
`tests/unit/_geometry_audit_helpers.py`（原语/端口/连通性/网格四类门），
每个模板的定向单测（`tests/unit/test_<模板>_template.py`）就是审计门槛
——先绿再真跑，这是纪律不是建议。

## 2. 真跑一个点

参照 `scripts/coupled_bpf_smoke.py` 的骨架（后台分离 + 日志轮询，长跑
纪律见下）：

```python
from pathlib import Path
from rfauto.adapters.em_solver_base import (
    EMSolverConfig, resolve_openems_exe)
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

work = Path("runs/my_smoke/pt1")
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(2.15, 2.65),
    mesh_resolution_mm=0.4, extra_params={"solve_timeout_s": 3600.0}))
assert solver.connect()
assert solver.build_geometry({"template": "mline",
                              "params": dict(TEMPLATE_NOMINAL["mline"])})
result = solver.solve()
assert result.success and result.s_params is not None
```

多端口模板注意：整 S 矩阵按 `excite_port=1..N` 渲染 N 份脚本、**进程
隔离**各跑一次后装配（进程内复用 CSX/端口包装器会踩绑定对象生命周期雷，
`render_script` docstring 有全文）。

**真跑纪律**（历史教训内核化，违反就是重跑几小时）：

- 长跑用后台分离进程 + 日志轮询，不占前台；
- 机器上已有其他求解在跑时先错峰——并发实测会把求解拖慢数倍；
- 预算外推：步数 ≈ 激励时长/dt，dt 按终网格最小格 CFL 实算； NrTS 触顶
  （能量只衰减到 −30~−46dB）即判未收敛，别把截断当物理；
- |S11|>1 先查脉冲截断（FC 窗要覆盖脉冲全程），再怀疑物理。

## 3. 判读：对着 meta.yaml 的 smoke_note 与健康门

1. 产物在 `work` 目录：`sparams.csv`（带掩码的 S 参数，单激励是零填充
   部分矩阵）、`port_beta.csv`（端口 β/引擎 Z0）、`et`/`port_ut_*`（
   时序收敛证据——`et` 是激励信号时间序列不是能量曲线，判收敛看
   port_ut 末段时间轴与末窗幅度）；
2. `rfauto runs health <run_id>`（或以 runs 目录为粒度调用
   `service.health_service.health_check_run`）走 G11 门：激励体积死、
   cost 退化、CFL 时间步塌缩、无源性/互易性/非物理增益——判据语义见
   docs/how-to/read-verdict-gates.md；
3. 各模板的预期口径在 `docs/templates/<模板>/meta.yaml`
   （`smoke_note`/`param_semantics` 字段），锚值出处见
   docs/rf_template_references.md。冒烟判据**先于真跑预声明**，不事后
   改门。

## 排错速查

| 症状 | 先查 |
|---|---|
| CalcPort IndexError | 网格最小间距塌缩（nm 级近重合线把 CFL 时间步压穿） |
| \|S11\|>1 | NrTS 触顶截断 / 激励体积为零（零宽盒、盒边未进网格） |
| 全带不耦合 | 端口面没贴 PML 边界 / 馈线止于域中成开路 stub |
| S 参数量级怪 | 单激励部分矩阵当满矩阵读了（认掩码载体） |
