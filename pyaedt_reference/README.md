# PyAEDT API Reference for RFAuto

> 本目录内容提取自 [PyAEDT](https://github.com/ansys/pyaedt) 官方源码（MIT License），
> 供开发参考；提取自 pyaedt 1.4.0 版本源码通读整理。

## 文件索引

| 文件 | 内容 |
|------|------|
| `api_quick_ref.md` | 关键方法签名速查（Hfss/Modeler/Constants/Object3d） |
| `examples_hfss.py` | 从官方测试提取的 HFSS 示例代码（6 个完整示例） |
| `port_setup.md` | 端口设置模式（5 种模式 + 常见错误表 + **真机验证补充：显式端口 sheet 模式、求解域边界约束、batch.log 调试法**） |
| `setup_sweep.md` | Setup + Sweep 设置模式（3 种创建方式 + 3 种扫描类型） |
| `modeler_primitives.md` | 3D 建模原语速查（体素 + 布尔 + 属性） |
| `material_mesh.md` | 材料管理 + 网格操作（新增） |
| `optimetrics.md` | Optimetrics 参数扫描/优化/DOE（新增） |
| `boundaries_fields.md` | 边界条件 + 远场/近场设置（新增） |
| `variables_hpc.md` | 变量管理 + HPC 选项 + 批处理求解（新增） |
| `constants_utils.md` | 常量 + 工具函数 + 错误类型（全阶段通用） |

## 核心发现（必读）

### 1. Import 路径
```python
from ansys.aedt.core import Hfss                    # 主入口
from ansys.aedt.core.generic.constants import Plane  # 平面常量
from ansys.aedt.core.generic.constants import Axis   # 轴常量
```

### 2. Hfss() 构造函数
```python
# ★ pyaedt 1.4.0 inspect.signature 真实签名（真机验证）
# Desktop(version=, non_graphical=, new_desktop=, close_on_exit=, student_version=, machine=, port=, aedt_process_id=)
# Hfss(project=, design=, solution_type=, setup=, version=, non_graphical=, new_desktop=, close_on_exit=, student_version=, machine=, port=, aedt_process_id=, remove_lock=)
# ★ 注意：参数名是 version= 不是 specified_version=（真机踩坑修正）
hfss = Hfss(
    project="my_project",      # 项目名
    design="my_design",        # 设计名
    solution_type="DrivenModal",  # 或 "Terminal"
    version="2023.1",          # AEDT 版本（不是 specified_version）
    new_desktop=True,          # 启动新实例
)
```

### 3. 关键方法参数名（pyaedt 1.4.0，inspect.signature 核实）
- `create_setup(name=)` — 不是 `setupname=`
- `create_linear_count_sweep(setup=, unit=, start_frequency=, stop_frequency=, num_of_freq_points=, name=)` — 注意 unit= 必填
- `analyze(setup=)` — 不需要 `name=`
- `export_touchstone(setup=, sweep=, output_file=, renormalization=, impedance=)` — 不是 setup_name/sweep_name
- `create_rectangle` — 在 modeler 上，不在 Hfss 类上
- `create_box` — 在 modeler 上，不在 Hfss 类上
- `wave_port(assignment=, name=, impedance=, renormalize=)` — assignment 传 face_id 最可靠
- `assign_radiation_boundary_to_objects(assignment=, name=)` — 传对象名
- `assign_radiation_boundary_to_faces(assignment=, name=)` — 传 face_id
- ★ Desktop 健康检查：用 `desktop.current_version` 属性，不是 `version_keys()`（真机踩坑）
- ★ Desktop 其他属性：`aedt_version`、`installed_versions`（都是 property）

### 4. 端口物理要点
- 微带线端口需要空气域（vacuum box）+ 辐射边界
- 传 face_id 让 pyaedt 自动选择积分线比手动指定更可靠
- `wave_port(assignment=face_id, name="port1", impedance=50)` — 最简形式

### 5. gRPC 稳定性
- 长时间求解后可能断连
- 用 `export_touchstone_on_completion(export=True)` 在求解前设置自动导出
- 不同 AEDT 版本稳定性不同，不做版本特定适配

### 6. 材料管理（新增）
```python
# 访问材料
mat = hfss.materials["copper"]
mat.conductivity = 5.8e7
mat.permittivity = 3.66

# 创建新材料
new_mat = hfss.materials.add_material("my_material")
new_mat.permittivity = 4.4
new_mat.conductivity = 0.02

# 材料属性
mat.is_conductor()    # 检查是否导体
mat.is_dielectric()   # 检查是否介质
mat.material_appearance = [0, 153, 153, 0.5]  # RGB + 透明度
```

### 7. 网格操作（新增）
```python
# 长度网格
hfss.mesh.assign_length_mesh("Box1", maximum_length=0.5, maximum_elements=1000)

# 肤深网格
hfss.mesh.assign_skin_depth("Box1", skin_depth="0.2mm", layers_number="2")

# 曲线元素
hfss.mesh.assign_curvilinear_elements("Box1", enable=True)
```

### 8. Optimetrics（新增）
```python
# 参数扫描
param = hfss.parametrics.add("arm_len", 18, 22, 5, "LinearCount")
param.analyze()

# 优化
opt = hfss.optimizations.add(
    calculation="dB(S(1,1))",
    ranges={"Freq": ("2.3GHz", "2.5GHz")},
    variables=["arm_len", "series_w"],
    optimization_type="Optimization",
)
opt.add_goal("dB(S(1,1))", {"Freq": ("2.3GHz", "2.5GHz")}, condition="<=", goal_value=-15)
opt.analyze()
```

### 9. 变量管理（新增）
```python
# 设置变量
hfss["w"] = "1.1mm"
hfss["$project_var"] = "50"  # 项目变量

# 变量操作
hfss.variable_manager["w"].numeric_value  # 获取数值
hfss.variable_manager["w"].units           # 获取单位
hfss.variable_manager.independent_variables  # 独立变量列表
hfss.variable_manager.dependent_variables    # 依赖变量列表
```

### 10. HPC 选项（新增）
```python
# 自定义 HPC
hfss.set_custom_hpc_options(cores=4, tasks=2, gpus=1)

# 批处理求解
hfss.solve_in_batch(cores=4, tasks=1, blocking=True)

# 监控
hfss.are_there_simulations_running  # 检查是否有仿真在运行
hfss.stop_simulations()             # 停止仿真
```

### 11. 导出结果（新增）
```python
# 导出所有结果
exported_files = hfss.export_results(export_folder="output/")

# 导出收敛数据
hfss.export_convergence(setup="Setup1", output_file="convergence.prof")

# 导出参数化结果
hfss.export_parametric_results("ParametricSetup1", "results.csv")
```

### 12. 边界条件（新增）
```python
# Perfect E
hfss.assign_perfect_e("Box1")

# Perfect H
hfss.assign_perfect_h("Box1")

# 辐射边界
hfss.assign_radiation_boundary_to_faces(face_id)

# 有限导电率
hfss.assign_finite_conductivity("Box1", material="copper")

# 阻抗边界
hfss.assign_impedance("Box1", resistance=50)
```

### 13. 远场/近场设置（新增）
```python
# 远场球
sphere = hfss.insert_infinite_sphere()
sphere.props["ThetaStart"] = "-90deg"
sphere.props["ThetaStop"] = "90deg"

# 近场矩形
rectangle = hfss.insert_near_field_rectangle()
```

### 14. 关键架构发现

**类继承链**：
```
Hfss → FieldAnalysis3D → Analysis → Design → PyAedtBase
         ↑                    ↑
    ScatteringMethods    CreateBoundaryMixin
```

**关键属性**：
- `hfss.modeler` — 3D 建模器
- `hfss.mesh` — 网格操作
- `hfss.materials` — 材料库
- `hfss.setups` — Setup 列表
- `hfss.parametrics` — 参数扫描
- `hfss.optimizations` — 优化
- `hfss.post` — 后处理
- `hfss.boundaries` — 边界列表
- `hfss.excitations` — 激励列表
- `hfss.field_setups` — 场设置

**Setup 类型映射**：
- `HFSS` → `SetupHFSS` (type=1)
- `SBR+` → `SetupSBR` (type=4)
- `Q3D` → `SetupQ3D` (type=14,30)
- `Icepak` → `SetupIcepak` (type=11,36)
- `Maxwell` → `SetupMaxwell` (type=5-10,56,58-60)
- `HFSS3DLayout` → `Setup3DLayout`
- `Circuit` → `SetupCircuit`
- `HFSSDrivenAuto` → `SetupHFSSAuto` (type=0)