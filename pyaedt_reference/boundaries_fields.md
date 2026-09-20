# 边界条件 + 远场/近场设置

## 边界条件类型

### Perfect E（理想电导体）
```python
hfss.assign_perfect_e(
    assignment="Box1",  # 对象名、面 ID 或列表
    name="my_perfect_e",
)
```

### Perfect H（理想磁导体）
```python
hfss.assign_perfect_h(
    assignment="Box1",
    name="my_perfect_h",
)
```

### 辐射边界
```python
hfss.assign_radiation_boundary_to_faces(
    assignment=face_id,  # 面 ID 或面 ID 列表
    name="my_radiation",
)
```

### 有限导电率
```python
hfss.assign_finite_conductivity(
    assignment="Box1",
    material="copper",
    use_thickness=True,
    thickness="0.2mm",
    name="my_finite_cond",
)
```

### 阻抗边界
```python
hfss.assign_impedance(
    assignment="Box1",
    resistance=50,
    reactance=0,
    name="my_impedance",
)
```

### Lumped RLC
```python
hfss.assign_lumped_rlc(
    assignment="Box1",
    resistance=50,
    inductance="1nH",
    capacitance="1pF",
    name="my_rlc",
)
```

### 对称边界
```python
hfss.assign_symmetry(
    assignment="Box1",
    symmetry_name="my_symmetry",
)
```

### 无限地平面
```python
hfss.assign_infinite_ground(
    assignment="Box1",
    use_adaptive=True,
    name="my_ground",
)
```

---

## 端口（激励）

### Wave Port
```python
# 方式 1：face_id（推荐）
faces = hfss.modeler.get_object_faces("trace")
port_face = min(faces, key=lambda f: hfss.modeler.get_face_center(f)[0])
hfss.wave_port(assignment=port_face, name="port1", impedance=50, renormalize=True)

# 方式 2：axis_directions
hfss.wave_port(
    assignment=rect_sheet,
    integration_line=hfss.axis_directions.XNeg,
    impedance=50,
    name="port1",
)

# 方式 3：两点列表
hfss.wave_port(
    assignment=rect_sheet,
    integration_line=[[0, 0, 0], [0, 0, 0.508]],
    impedance=50,
    name="port1",
)

# 方式 4：微带线专用
hfss.wave_port(
    assignment=rect_sheet,
    is_microstrip=True,
    vfactor=3,  # 垂直扩展 3 倍基板厚度
    hfactor=5,  # 水平扩展 5 倍线宽
    impedance=50,
    name="ms_port",
)
```

### Lumped Port
```python
# 方式 1：对象名 + 参考
hfss.lumped_port(
    assignment="trace",
    reference="ground",
    integration_line=hfss.axis_directions.ZPos,
    impedance=50,
    name="lumped_port",
)

# 方式 2：face_id
face_id = hfss.modeler.get_object_faces("trace")[0]
hfss.lumped_port(assignment=face_id, impedance=50, name="lumped_port")
```

---

## 远场设置 (Far Field)

### 无限球
```python
sphere = hfss.insert_infinite_sphere(
    name="my_far_field",
    definition="Theta-Phi",  # "Theta-Phi" | "El Over Az" | "Az Over El"
)
sphere.props["ThetaStart"] = "-90deg"
sphere.props["ThetaStop"] = "90deg"
sphere.props["ThetaStep"] = "2deg"
sphere.props["PhiStart"] = "0deg"
sphere.props["PhiStop"] = "360deg"
sphere.props["PhiStep"] = "2deg"
```

### 属性
```python
# 定义类型
sphere.definition = "Theta-Phi"

# 极化
sphere.polarization = "Linear"
sphere.slant_angle = 45  # 当 polarization="Slant" 时

# 角度范围 (Theta-Phi)
sphere.theta_start = -90
sphere.theta_stop = 90
sphere.theta_step = 2
sphere.phi_start = 0
sphere.phi_stop = 360
sphere.phi_step = 2

# 角度范围 (Az Over El / El Over Az)
sphere.azimuth_start = -180
sphere.azimuth_stop = 180
sphere.azimuth_step = 2
sphere.elevation_start = -90
sphere.elevation_stop = 90
sphere.elevation_step = 2

# 坐标系
sphere.use_local_coordinate_system = True
sphere.local_coordinate_system = "my_cs"

# 辐射面
sphere.use_custom_radiation_surface = True
sphere.custom_radiation_surface = "my_face_list"
```

---

## 近场设置 (Near Field)

### 矩形近场
```python
rectangle = hfss.insert_near_field_rectangle(
    name="my_near_field",
)
```

### 盒子近场
```python
box = hfss.insert_near_field_box(
    name="my_near_field_box",
)
```

### 球近场
```python
sphere = hfss.insert_near_field_sphere(
    name="my_near_field_sphere",
)
```

### 线近场
```python
line = hfss.insert_near_field_line(
    name="my_near_field_line",
)
```

---

## 边界对象操作

```python
# 列出所有边界
for bound in hfss.boundaries:
    print(f"{bound.name}: {bound.type}")

# 获取边界
bound = hfss.boundaries[0]
bound.name   # 边界名
bound.type   # 边界类型
bound.props  # 边界属性

# 更新边界
bound.props["Resistance"] = 100
bound.update()

# 删除边界
bound.delete()

# 更新赋值
bound.update_assignment()
```

---

## 激励对象操作

```python
# 列出所有激励
for exc in hfss.excitations:
    print(f"{exc.name}: {exc.type}")

# 按类型分组
hfss.excitations_by_type  # dict[str, list[BoundaryObject]]
```