# PyAEDT API Quick Reference

> 从 hfss.py / primitives_3d.py / analysis_hf.py 提取的关键方法签名。

## Hfss 类

### 构造函数
```python
Hfss(project, design, solution_type, version, new_desktop, ...)
```

### 端口
```python
# Wave Port（推荐用于微带线）
wave_port(
    assignment: int | Object3d | FacePrimitive,  # 面 ID 或对象
    reference: int | str | list | Object3d = None,
    create_port_sheet: bool = False,
    integration_line: int | Gravity | list[float] = 0,  # 或 axis_directions.XNeg 等
    modes: int = 1,
    impedance: float = 50,
    name: str = None,
    renormalize: bool = True,
    deembed: float = 0,
    is_microstrip: bool = False,
    vfactor: int = 3,   # 微带线垂直因子
    hfactor: int = 5,   # 微带线水平因子
) -> BoundaryObject

# Lumped Port
lumped_port(
    assignment: str | int | list,
    reference: Object3d | int | list | None = None,
    create_port_sheet: bool = False,
    integration_line: int | Gravity | list[float] = 0,
    impedance: float = 50,
    name: str = None,
    renormalize: bool = True,
) -> BoundaryObject
```

### Setup
```python
create_setup(
    name: str = "MySetupAuto",
    setup_type: str | None = None,  # "HFSSDriven", "HFSSDrivenAuto", "HFSSEigen", etc.
    **kwargs  # Frequency, MaximumPasses, DeltaS, etc.
) -> SetupHFSS | SetupHFSSAuto
```

### Sweep
```python
create_linear_count_sweep(
    setup: str,              # Setup 名称
    unit: str,               # "GHz", "MHz", etc.
    start_frequency: float,  # 起始频率
    stop_frequency: float,   # 终止频率
    num_of_freq_points: int = None,
    name: str = None,
    save_fields: bool = True,
    sweep_type: str = "Discrete",
) -> SweepHFSS
```

### 求解
```python
analyze(setup: str) -> bool
```

### 导出
```python
export_touchstone(
    setup: str = None,
    sweep: str = None,
    output_file: str = None,
    renormalization: bool = False,
    impedance: float = None,
) -> str | bool

export_touchstone_on_completion(
    export: bool = True,
    output_dir: str | Path = None,
) -> bool
```

## Modeler 原语

### create_box
```python
create_box(
    origin: list,      # [x, y, z]
    sizes: list,       # [dx, dy, dz]
    name: str = None,
    material: str = None,
) -> Object3d
```

### create_rectangle
```python
create_rectangle(
    orientation: str | int | Plane,  # 0=XY, 1=YZ, 2=XZ
    origin: list,                    # [x, y, z]
    sizes: list,                     # [width, height]
    name: str = None,
    material: str = None,
) -> Object3d
```

### create_circle
```python
create_circle(
    orientation: str | int | Plane,
    center: list,
    radius: float,
    name: str = None,
) -> Object3d
```

### create_cylinder
```python
create_cylinder(
    orientation: str | int | Axis,  # 0=X, 1=Y, 2=Z
    center: list,
    radius: float,
    height: float,
    draft_angle: float = 0,
    name: str = None,
    material: str = None,
) -> Object3d
```

## 常量

### Plane（用于 create_rectangle/create_circle）
```python
from ansys.aedt.core.generic.constants import Plane
Plane.XY  # 0
Plane.YZ  # 1
Plane.XZ  # 2
```

### Axis（用于 create_cylinder）
```python
from ansys.aedt.core.generic.constants import Axis
Axis.X  # 0
Axis.Y  # 1
Axis.Z  # 2
```

### axis_directions（用于端口积分线）
```python
hfss.axis_directions.XNeg  # -X 方向
hfss.axis_directions.XPos  # +X 方向
hfss.axis_directions.YNeg
hfss.axis_directions.YPos
hfss.axis_directions.ZNeg
hfss.axis_directions.ZPos
```

## Object3d 属性

```python
obj.id           # 对象 ID
obj.name         # 对象名称
obj.faces        # 面列表
obj.edges        # 边列表
obj.vertices     # 顶点列表
obj.material_name  # 材料名称
obj.center       # 中心坐标

# 面操作
face_id = obj.faces[0].id
face_center = obj.faces[0].center
face_area = obj.faces[0].area
```

## 常用 Modeler 操作

```python
# 获取对象
hfss.modeler.get_object_by_name("my_box")
hfss.modeler.get_objects_by_material("copper")
hfss.modeler.get_object_faces("my_box")

# 布尔运算
hfss.modeler.unite(["box1", "box2"])
hfss.modeler.subtract("box1", "box2", keep_originals=True)
hfss.modeler.intersect(["box1", "box2"])

# 材料赋值
obj.material_name = "copper"
hfss.modeler["my_box"].material_name = "Rogers RO4350 (tm)"

# 变量
hfss["w"] = "1.1mm"
hfss["l"] = "20mm"
```