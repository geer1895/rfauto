# 3D 建模原语速查

## 基本体素

### Box（盒子）
```python
box = hfss.modeler.create_box(
    origin=[x, y, z],      # 起点坐标
    sizes=[dx, dy, dz],    # 尺寸
    name="my_box",
    material="copper",
)
```

### Cylinder（圆柱）
```python
cyl = hfss.modeler.create_cylinder(
    orientation=Axis.Z,    # 轴方向：Axis.X/Y/Z
    center=[x, y, z],
    radius=3.0,
    height=80.0,
    draft_angle=0,         # 拔模角度
    name="my_cylinder",
    material="copper",
)
```

### Sphere（球）
```python
sphere = hfss.modeler.create_sphere(
    center=[x, y, z],
    radius=10.0,
    name="my_sphere",
)
```

### Rectangle（矩形）
```python
rect = hfss.modeler.create_rectangle(
    orientation=Plane.YZ,  # 平面：Plane.XY/YZ/XZ
    origin=[x, y, z],
    sizes=[width, height],
    name="my_rect",
)
```

### Circle（圆）
```python
circle = hfss.modeler.create_circle(
    orientation=Plane.YZ,
    center=[x, y, z],
    radius=10.0,
    name="my_circle",
)
```

## 布尔运算

### Unite（合并）
```python
hfss.modeler.unite(["box1", "box2"])
# 或
hfss.modeler.unite([box1_obj, box2_obj])
```

### Subtract（减去）
```python
hfss.modeler.subtract(
    blank="outer_box",
    tool="inner_box",
    keep_originals=True,
)
```

### Intersect（交集）
```python
hfss.modeler.intersect(["box1", "box2"])
```

### Duplicate（复制）
```python
hfss.modeler.duplicate_along_line(
    assignment="my_box",
    vector=[10, 0, 0],
    clones=3,
)
```

## 对象操作

### 获取对象
```python
obj = hfss.modeler.get_object_by_name("my_box")
obj = hfss.modeler["my_box"]  # 简写
```

### 获取面
```python
faces = hfss.modeler.get_object_faces("my_box")
face_id = faces[0]
face_center = hfss.modeler.get_face_center(face_id)
```

### 获取边
```python
edges = hfss.modeler.get_object_edges("my_box")
```

### 材料赋值
```python
obj.material_name = "copper"
# 或
hfss.modeler["my_box"].material_name = "Rogers RO4350 (tm)"
```

## 变量

### 设置变量
```python
hfss["w"] = "1.1mm"
hfss["l"] = "20mm"
hfss["h"] = "0.508mm"
```

### 使用变量表达式
```python
hfss.modeler.create_box(
    ["-w/2", "-l/2", "0"],
    ["w", "l", "h"],
    name="substrate",
)
```

## 常用常量

```python
from ansys.aedt.core.generic.constants import Plane, Axis

# 平面（用于 create_rectangle/create_circle）
Plane.XY  # 0
Plane.YZ  # 1
Plane.XZ  # 2

# 轴（用于 create_cylinder）
Axis.X  # 0
Axis.Y  # 1
Axis.Z  # 2
```

## Position 对象

```python
pos = hfss.modeler.Position(0, 0, 0)
# 或直接用列表
[0, 0, 0]
```

## 对象属性

```python
obj.id            # 对象 ID
obj.name          # 对象名称
obj.faces         # 面列表
obj.edges         # 边列表
obj.vertices      # 顶点列表
obj.material_name # 材料名称
obj.center        # 中心坐标
obj.bounding_box  # 包围盒 [xmin, ymin, zmin, xmax, ymax, zmax]
```

## 面属性

```python
face = obj.faces[0]
face.id           # 面 ID
face.center       # 面中心
face.area         # 面面积
face.normal       # 面法向量
face.edges        # 面边列表
```