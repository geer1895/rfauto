# 材料管理 + 网格操作

## 材料管理

### 访问材料
```python
# 获取现有材料
mat = hfss.materials["copper"]
mat = hfss.materials["Rogers RO4350 (tm)"]

# 列出所有材料
for name in hfss.materials.material_keys:
    print(name)
```

### 材料属性
```python
# 基本属性
mat.permittivity = 3.66
mat.permeability = 1.0
mat.conductivity = 5.8e7
mat.dielectric_loss_tangent = 0.0037
mat.magnetic_loss_tangent = 0.0
mat.thermal_conductivity = 0.69
mat.mass_density = 1680
mat.specific_heat = 900
mat.thermal_expansion_coefficient = 1.4e-5
mat.youngs_modulus = 1.1e10
mat.poissons_ratio = 0.28

# 检查材料类型
mat.is_conductor(threshold=100000)  # 是否导体
mat.is_dielectric(threshold=100000)  # 是否介质

# 外观
mat.material_appearance = [R, G, B, transparency]  # 0-255, 0-1
```

### 创建新材料
```python
new_mat = hfss.materials.add_material("my_substrate")
new_mat.permittivity = 4.4
new_mat.dielectric_loss_tangent = 0.02
new_mat.conductivity = 0.0
new_mat.mass_density = 1900
new_mat.thermal_conductivity = 0.3
```

### 频率相关材料
```python
# Djordjevic-Sarkar 模型
mat.set_djordjevic_sarkar_model(
    dk=4.4,           # 介电常数
    df=0.02,          # 损耗角正切
    frequency=1e9,    # 输入频率 (Hz)
    sigma_dc=1e-12,   # DC 电导率
    freq_hi=159.15494e9,  # 高频角
)

# 非线性材料 (BH 曲线)
mat.permeability = [[0, 0], [0.1, 500], [0.3, 1000], [0.5, 1500]]
```

### 铁芯损耗
```python
# 电工钢铁芯损耗
mat.set_electrical_steel_coreloss(kh=100, kc=0.5, ke=0, kdc=0)

# 功率铁氧体铁芯损耗
mat.set_power_ferrite_coreloss(cm=100, x=2.0, y=2.5)

# BP 曲线铁芯损耗
mat.set_bp_curve_coreloss(
    points=[[0, 0], [0.1, 100], [0.2, 400], [0.3, 900]],
    frequency=60,
    thickness="0.5mm",
)
```

### 热修饰符
```python
# 闭式热修饰符
mat.conductivity.add_thermal_modifier_closed_form(
    tref=22, c1=0.004, c2=0, tl=-273.15, tu=1000, units="cel"
)

# 自由形式热修饰符
mat.conductivity.add_thermal_modifier_free_form(
    "if(Temp > 1000cel, 5.8e7, 5.8e7 * (1 + 0.004 * (Temp - 22cel)))"
)

# 数据集热修饰符
mat.conductivity.add_thermal_modifier_dataset("$ds1")
```

---

## 网格操作

### 长度网格
```python
hfss.mesh.assign_length_mesh(
    assignment="Box1",           # 对象名或面 ID 列表
    inside_selection=True,       # 是否在选择内部
    maximum_length=0.5,          # 最大单元长度 (mm)
    maximum_elements=1000,       # 最大单元数
    name="my_length_mesh",       # 网格操作名称
)
```

### 肤深网格
```python
hfss.mesh.assign_skin_depth(
    assignment="Box1",
    skin_depth="0.2mm",          # 肤深
    maximum_elements=1000,       # 最大单元数
    triangulation_max_length="0.1mm",  # 三角化最大长度
    layers_number="2",           # 层数
    name="my_skin_depth",
)
```

### 曲线元素
```python
hfss.mesh.assign_curvilinear_elements(
    assignment="Box1",
    enable=True,
    name="my_curvilinear",
)
```

### 曲率提取
```python
hfss.mesh.assign_curvature_extraction(
    assignment="Box1",
    disabled_for_faceted=True,
    name="my_curvature",
)
```

### 旋转层网格（Maxwell）
```python
hfss.mesh.assign_rotational_layer(
    assignment="Box1",
    layers_number=3,
    total_thickness="1mm",
    name="my_rotational",
)
```

### 边缘切割网格（Maxwell）
```python
hfss.mesh.assign_edge_cut(
    assignment="Box1",
    layer_thickness="1mm",
    name="my_edge_cut",
)
```

### 密度控制（Maxwell）
```python
hfss.mesh.assign_density_control(
    assignment="Box1",
    refine_inside=True,
    maximum_element_length="1mm",
    layers_number=3,
    name="my_density",
)
```

### 圆柱间隙（Maxwell）
```python
hfss.mesh.assign_cylindrical_gap(
    entity="Box1",
    clone_mesh=True,
    band_mapping_angle=1.0,
    moving_side_layers=1,
    static_side_layers=1,
    name="my_cylindrical_gap",
)
```

### 网格操作管理
```python
# 列出所有网格操作
for mop in hfss.mesh.meshoperations:
    print(f"{mop.name}: {mop.type}")

# 删除网格操作
hfss.mesh.meshoperations[0].delete()

# 网格操作名称
hfss.mesh.meshoperation_names
```

### 初始网格设置
```python
# 从滑块设置初始网格
hfss.mesh.assign_initial_mesh_from_slider(
    sliderpos=3,  # 1-10，1=粗糙，10=精细
)

# 手动设置初始网格
hfss.mesh.assign_initial_mesh(
    apply_curvilinear=True,
    use_auto_simplify=True,
    defeature_length="1mm",
)
```