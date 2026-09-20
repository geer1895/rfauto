# Setup + Sweep 设置模式（从测试用例补充）

## Setup 创建（从 test_setup.py 提取）

### 基本创建
```python
from ansys.aedt.core.generic.constants import Setups

# 方式 1：使用常量
setup1 = hfss.create_setup("My_HFSS_Setup", Setups.HFSSDrivenDefault)

# 方式 2：使用 kwargs
setup2 = hfss.create_setup("MulitFreqSetup", MultipleAdaptiveFreqsSetup=["1GHz", "2GHz"], MaximumPasses=3)

# 方式 3：自动命名
setup3 = hfss.create_setup(Frequency=["1GHz", "2GHz"], MaximumPasses=3)
```

### Setup 属性操作
```python
# 访问属性
setup.props["SaveRadFieldsOnly"]
setup["SaveRadFieldsonly"]  # 别名

# 修改属性
setup.props["Frequency"] = "2.4GHz"
setup.props["MaximumPasses"] = 15
setup.props["MaxDeltaS"] = 0.02
setup.update()

# 启用/禁用
setup.disable()
setup.enable()
```

### 自适应设置
```python
# 多频率自适应
setup.enable_adaptive_setup_multifrequency([1, 2, 3])
assert setup.props["SolveType"] == "MultiFrequency"

# 宽带自适应
setup.enable_adaptive_setup_broadband(1, 2.5, 10, 0.01)
assert setup.props["MultipleAdaptiveFreqsSetup"]["Low"] == "1GHz"

# 单频率自适应
setup.enable_adaptive_setup_single(3.5)
assert setup.props["Frequency"] == "3.5GHz"
```

### 矩阵收敛
```python
setup.use_matrix_convergence(
    entry_selection=0,
    ignore_phase_when_mag_is_less_than=0.015,
    all_diagonal_entries=True,
    max_delta=0.03,
    max_delta_phase=8,
    custom_entries=None,
)
```

### 删除 Setup
```python
setup.delete()
# 或
hfss.delete_setup("My_HFSS_Setup")
```

---

## Sweep 创建（从 test_setup.py 提取）

### 基本 Sweep
```python
# 添加 sweep
sweep1 = setup.add_sweep("MyFrequencySweep")
sweep1.props["RangeStart"] = "1Hz"
sweep1.props["RangeEnd"] = "2GHz"
sweep1.update()

# Sweep 类型
sweep1.props["Type"] = "Fast"  # "Discrete" | "Interpolating" | "Fast"
sweep1.props["SaveFields"] = True
sweep1.update()
```

### 频率扫描
```python
# 方式 1：create_frequency_sweep
sweep3 = setup.create_frequency_sweep(start_frequency=1, stop_frequency="500MHz")
sweep3.props["Type"] == "Discrete"

# 方式 2：add_sweep with kwargs
sweep5 = setup.add_sweep(
    "DiscSweep5",
    sweep_type="Discrete",
    RangeStart="1GHz",
    RangeEnd="2GHz",
    RangeStep="0.5GHz",
    SaveFields=True,
)
```

### 子范围
```python
# 添加子范围
setup.add_subrange("LinearStep", 1, 10, 0.1, clear=False)
setup.add_subrange("LogScale", 1, 10, 10, clear=False)
setup.add_subrange("SinglePoint", 2.4, clear=False)
```

### 获取 Sweep
```python
# 获取 setup 的所有 sweep
sweeps = hfss.get_sweeps("My_HFSS_Setup")

# 获取所有 setup
setups = hfss.get_setups()
```

---

## Setup 类型常量

```python
from ansys.aedt.core.generic.constants import Setups

# HFSS
Setups.HFSSDrivenDefault  # 驱动模态默认
Setups.HFSSDrivenAuto     # 自动驱动模态

# 其他
Setups.HFSSEigen          # 本征模
Setups.HFSSTransient      # 瞬态
Setups.HFSSSBRPlus        # SBR+
```

---

## 从 test_variable_manager.py 提取的变量操作

### 设置变量
```python
# 设计变量
hfss["Var1"] = "1rpm"
hfss["Var2"] = 12
hfss["Var3"] = "Var1 * Var2"  # 依赖变量

# 项目变量
hfss["$Test_Global1"] = "5rad"
hfss["$Test_Global2"] = -1.0
hfss["$Test_Global3"] = "$Test_Global2*$Test_Global1"

# 使用 set_variable
hfss.variable_manager.set_variable("p2", "20mm", circuit_parameter=False)
```

### 访问变量
```python
# 获取变量值
var = hfss["Var1"]
var = hfss.variable_manager["Var1"].expression
var = hfss.variable_manager["Var1"].numeric_value
var = hfss.variable_manager["Var1"].evaluated_value
var = hfss.variable_manager["Var1"].si_value
var = hfss.variable_manager["Var1"].units

# 变量分类
independent = hfss.variable_manager.independent_variable_names
dependent = hfss.variable_manager.dependent_variable_names
project_vars = hfss.variable_manager.independent_project_variable_names
design_vars = hfss.variable_manager.independent_design_variable_names
```

### 删除变量
```python
del hfss["$test2"]
del hfss["test"]
```

### 变量属性
```python
var = hfss.variable_manager["Var1"]
var.description      # 描述
var.hidden           # 是否隐藏
var.read_only        # 只读
var.post_processing  # 后处理变量
var.sweep            # 是否可扫描
var.is_optimization_enabled
var.is_sensitivity_enabled
var.is_statistical_enabled
```

### 公式计算
```python
hfss["Var1"] = 3
hfss["Var2"] = "12deg"
hfss["Var3"] = "Var1 * Var2"
assert hfss.variable_manager.variables["Var3"].numeric_value == 36.0
assert hfss.variable_manager.variables["Var3"].units == "deg"

hfss["$PrjVar1"] = "2*pi"
hfss["$PrjVar2"] = 45
hfss["$PrjVar3"] = "sqrt(34 * $PrjVar2/$PrjVar1)"
```

---

## 从 test_materials.py 提取的材料操作

### 创建材料
```python
mat1 = hfss.materials.add_material("new_copper2")
mat1.conductivity = 59000000000
mat1.permittivity = 5
mat1.dielectric_loss_tangent = 0.1
mat1.magnetic_loss_tangent = 0.2
mat1.mass_density = 100
mat1.thermal_conductivity = 5
mat1.youngs_modulus = 1000
mat1.poissons_ratio = [1, 2, 3]  # 各向异性
mat1.thermal_conductivity = [1, 2, 3, 4, 5, 6, 7, 8, 9]  # 张量
```

### 非线性材料
```python
mat1.permeability = [[0, 0], [30, 40], [50, 60]]  # BH 曲线
mat1.permeability.type == "nonlinear"
mat1.permeability.set_non_linear(x_unit="Oe", y_unit="gauss")
```

### 铁芯损耗
```python
mat1.set_electrical_steel_coreloss(1, 2, 3, 4, 0.002)
mat1.set_hysteresis_coreloss(1, 2, 3, 4, 0.002)
mat1.set_bp_curve_coreloss([[0, 0], [10, 10], [20, 20]])
mat1.set_power_ferrite_coreloss()
mat1.get_curve_coreloss_type()  # "Electrical Steel" | "Hysteresis Model" | "B-P Curve" | "Power Ferrite"
```

### 材料外观
```python
mat1.material_appearance = [11, 22, 0, 0.5]  # RGB + 透明度
```

### 导入导出
```python
hfss.materials.export_materials_to_file("materials.json")
hfss.materials.import_materials_from_file("mats.json")
hfss.materials.import_materials_from_excel("mats.xlsx")
hfss.materials.import_materials_from_workbench("EngineeringData.xml")
```

### 材料扫描
```python
hfss.materials.add_material_sweep(["copper", "aluminum", "FR4_epoxy"], "sweep_material")
```

### 检查材料
```python
mat.is_used  # 是否被使用
mat.is_conductor()
mat.is_dielectric()
```

---

## 从 test_mesh.py 提取的网格操作

### 模型分辨率
```python
mr1 = hfss.mesh.assign_model_resolution(o, 1e-4, "ModelRes1")
mr1.props["DefeatureLength"] = "0.1mm"
mr1.update()
```

### 表面网格
```python
surface = hfss.mesh.assign_surface_mesh(o.id, 3, "Surface")
surface.props["SliderMeshSettings"] == 3
```

### 手动表面网格
```python
surface = hfss.mesh.assign_surface_mesh_manual(o.id, 1e-6, aspect_ratio=3, name="Surface_Manual")
surface.props["SurfDev"] = 1e-6
surface.props["NormalDev"] = "1"
surface.props["AspectRatio"] = 20
```

### 曲率提取（SBR+）
```python
curv = hfss.mesh.assign_curvature_extraction(box.name)
curv.props["DisableForFacetedSurfaces"]
```

### Maxwell 网格
```python
# 旋转层
rot = maxwell_app.mesh.assign_rotational_layer(o.name, total_thickness="5mm", name="Rotational")
rot.props["Number of Layers"] == "3"
rot.props["Total Layer Thickness"] == "5mm"

# 边缘切割
edge_cut = maxwell_app.mesh.assign_edge_cut(o.name, name="Edge")
edge_cut.props["Layer Thickness"] == "1mm"

# 密度控制
dens = maxwell_app.mesh.assign_density_control(o.name, maximum_element_length=10000, name="Density")
dens.props["RestrictMaxElemLength"]
dens.props["MaxElemLength"] == 10000
dens.props["RestrictLayersNum"]
dens.props["LayersNum"] == "1"
```

---

## 收敛信息提取（pyaedt 1.4.0 · 实测补充）

自适应求解的 passes / delta_s **真值不能用** `getattr(setup, "passes", 0)`（1.4.0 恒为 0）。
正确 API 是 `setup.get_profile()`（返回 `Profiles` 映射；类在 `ansys.aedt.core.modules.profile`）：

```python
profiles = setup.get_profile()          # Profiles (Mapping)
key = next(iter(profiles.keys()))
sim = profiles[key]                     # SimulationProfile
passes = sim.num_adaptive_passes        # = sum("Pass" in s for s in adaptive_pass.process_steps)

# delta_s_final：末次自适应 Pass 的 "Max Mag. Delta S" → delta_s_max
ap = sim.adaptive_pass                  # ProfileStep（来自 "Adaptive Meshing Group"）
pass_names = [s for s in (ap.process_steps or []) if "Pass" in s]
last = ap.steps[pass_names[-1]]         # 末次 Pass 的 ProfileStep
delta_s = float(getattr(last, "delta_s_max", 0.0) or 0.0)
```

要点：
- `ProfileStep.__init__` 按 `PROFILE_PROP_MAPPING` 把属性映射为成员，如
  `"Max Mag. Delta S" → delta_s_max (float)`、`"Tetrahedra" → num_tets (int)`
- `Profiles` 是 Mapping 子类，空映射真值为 False（判空用 `not profiles`，勿依赖 `len`）
- 工程封装：`HfssAdapter._extract_convergence(setup)` → `(passes, delta_s_final)`，
  任何异常回退 `(0, 0.0)` 不穿透（见 `src/rfauto/adapters/hfss_adapter.py`、`tests/unit/test_hfss_convergence.py`）

---

## 真机接入配置（P2 实测补充）

- **import 名**：包实际是 `ansys.aedt.core`（`import pyaedt` 是旧名，会 `ModuleNotFoundError`）。
  连接用 `from ansys.aedt.core import Desktop, Hfss`（见 `src/rfauto/adapters/hfss_session.py`，它是延迟导入）。
- **Hfss 构造**：`Hfss(desktop=d)` 是**错误**的（1.4.0 `Hfss.__init__` 无 `desktop` 参数）。
  正确模式：`d = Desktop(version=, non_graphical=)` 先起桌面，再
  `Hfss(version=, non_graphical=, new_desktop=False)` 复用同一桌面。
- **版本**：`HfssSession.connect` 默认 `desktop_version="2024.1"`；当目标机是 AEDT 2023R1 时
  必须显式传 `"2023R1"`，否则连错版本失败（版本误判坑）。`configs/settings.yaml` 现无
  `desktop_version` 字段——真机接入时需在 connect settings 里注入。
- **路径**：`RFAUTO_AEDT_PATH`（加载优先级 env > settings.yaml > 默认；指向
  本机 AEDT Win64 安装目录）。