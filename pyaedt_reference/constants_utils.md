# PyAEDT 常量 + 工具函数速查（全阶段通用）

## 常量（from ansys.aedt.core.generic.constants）

### 平面/轴/方向
```python
from ansys.aedt.core.generic.constants import Plane, Axis, Gravity

# 平面（用于 create_rectangle/create_circle）
Plane.YZ  # 0 - YZ 平面
Plane.ZX  # 1 - ZX 平面
Plane.XY  # 2 - XY 平面

# 轴（用于 create_cylinder）
Axis.X  # 0
Axis.Y  # 1
Axis.Z  # 2

# 方向（用于端口积分线、gravity 等）
Gravity.XNeg  # 0 - -X 方向
Gravity.YNeg  # 1
Gravity.ZNeg  # 2
Gravity.XPos  # 3
Gravity.YPos  # 4
Gravity.ZPos  # 5

# HFSS 也可以用：
hfss.axis_directions.XNeg  # 等同于 Gravity.XNeg
```

### HFSS 解决方案类型
```python
from ansys.aedt.core.generic.constants import SolutionsHfss

SolutionsHfss.DrivenModal      # "Modal" - 驱动模态
SolutionsHfss.DrivenTerminal   # "Terminal" - 驱动终端
SolutionsHfss.EigenMode        # "Eigenmode" - 本征模
SolutionsHfss.Transient        # "Transient Network" - 瞬态
SolutionsHfss.SBR              # "SBR+" - 射线追踪
SolutionsHfss.CharacteristicMode  # "Characteristic Mode"
```

### Setup 类型常量
```python
from ansys.aedt.core.generic.constants import Setups

# HFSS
Setups.HFSSDrivenAuto     # 0 - 自动驱动模态
Setups.HFSSDrivenDefault  # 1 - 驱动模态默认
Setups.HFSSEigen          # 2 - 本征模
Setups.HFSSTransient      # 3 - 瞬态
Setups.HFSSSBR            # 4 - SBR+

# Maxwell
Setups.MaxwellTransient   # 5
Setups.Magnetostatic      # 6
Setups.EddyCurrent        # 7
Setups.Electrostatic      # 8

# Circuit
Setups.NexximLNA          # 15
Setups.NexximDC           # 16
Setups.NexximTransient    # 17

# Q3D
Setups.Matrix             # 14

# Icepak
Setups.SteadyState        # 11
Setups.Transient          # 36
```

### Maxwell 3D 解决方案类型
```python
from ansys.aedt.core.generic.constants import SolutionsMaxwell3D

SolutionsMaxwell3D.Transient       # "Transient"
SolutionsMaxwell3D.Magnetostatic   # "Magnetostatic"
SolutionsMaxwell3D.EddyCurrent     # "AC Magnetic"
SolutionsMaxwell3D.ElectroStatic   # "Electrostatic"
SolutionsMaxwell3D.DCConduction    # "DC Conduction"
SolutionsMaxwell3D.ACMagnetic      # "AC Magnetic"
```

### 单位转换
```python
from ansys.aedt.core.generic.constants import unit_converter, AEDT_UNITS

# 单位转换
value = unit_converter(
    values=1.0,
    unit_system="Length",
    input_units="mm",
    output_units="meter",
)
# 结果: 0.001

# 单位系统
AEDT_UNITS["Length"]  # {"meter": 1.0, "mm": 0.001, "cm": 0.01, ...}
AEDT_UNITS["Freq"]    # {"Hz": 1.0, "MHz": 1e6, "GHz": 1e9, ...}
```

### 数学常量
```python
from ansys.aedt.core.generic.constants import (
    RAD2DEG, DEG2RAD, SpeedOfLight,
    db20, db10, dbw,
)

# 转换
db20(0.5)          # 20*log10(0.5) = -6.02 dB
db20(-6.02, inverse=False)  # 10^(-6.02/20) = 0.5
db10(10.0)         # 10*log10(10) = 10 dB

# 物理常量
SpeedOfLight       # 299792458.0 m/s
```

---

## 数字工具（from ansys.aedt.core.generic.numbers_utils）

### 变量值分解
```python
from ansys.aedt.core.generic.numbers_utils import decompose_variable_value, is_number, Quantity

# 分解变量值
value, unit = decompose_variable_value("10mm")    # (10.0, 'mm')
value, unit = decompose_variable_value("2.4GHz")  # (2.4, 'GHz')
value, unit = decompose_variable_value("1.1")     # (1.1, '')

# 检查是否为数字
is_number("1.1mm")  # False
is_number("1.1")    # True
is_number(1.1)      # True

# Quantity 对象（带单位的数字）
q = Quantity("10mm")
q.unit_system     # "Length"
q.to("cm")        # 1cm
q.to("meter")     # 0.01m
```

### 精度比较
```python
from ansys.aedt.core.generic.numbers_utils import is_close

is_close(1.0, 1.0 + 1e-10)  # True
is_close(1.0, 1.1)          # False
```

---

## 通用方法（from ansys.aedt.core.generic.general_methods）

### 函数装饰器
```python
from ansys.aedt.core.generic.general_methods import pyaedt_function_handler

# 用于所有 AEDT 交互函数的装饰器
# 自动处理：异常捕获、日志记录、deprecated kwargs
@pyaedt_function_handler()
def my_function(value):
    return value + 1

# 也可以直接用
@pyaedt_function_handler
def my_function(value):
    return value + 1
```

### 重试机制
```python
from ansys.aedt.core.generic.general_methods import _retry_ntimes

# 重试 n 次
result = _retry_ntimes(3, some_function, arg1, arg2)
```

### 过滤器
```python
from ansys.aedt.core.generic.general_methods import filter_tuple, filter_string

# 过滤元组
filter_tuple("(Port1,Port2)", "Port*", "Port2")  # True

# 过滤字符串
filter_string("S(1,1)", "S(1,*)")  # True
```

### 版本检查
```python
from ansys.aedt.core.generic.general_methods import get_version_and_release

version, release = get_version_and_release("2025.1")
# version = "2025", release = "1"
```

### 平台检查
```python
from ansys.aedt.core.generic.general_methods import is_linux, is_windows, is_macos

if is_windows:
    # Windows 特定代码
    pass
```

---

## PropsManager（属性管理基类）

```python
from ansys.aedt.core.generic.general_methods import PropsManager

# 所有 Setup、Boundary 等的基类
# 支持：
setup["Frequency"]           # __getitem__
setup["Frequency"] = "2.4GHz"  # __setitem__
setup.available_properties    # 列出所有可用属性
setup.update()                # 更新到 AEDT
```

---

## 错误类型（from ansys.aedt.core.internal.errors）

```python
from ansys.aedt.core.internal.errors import (
    AEDTRuntimeError,      # AEDT 运行时错误
    GrpcApiError,          # gRPC API 错误
    MethodNotSupportedError,  # 方法不支持
)

# 使用
try:
    hfss.some_method()
except GrpcApiError as e:
    print(f"gRPC 错误: {e}")
except AEDTRuntimeError as e:
    print(f"AEDT 错误: {e}")
```

---

## 文件工具（from ansys.aedt.core.generic.file_utils）

```python
from ansys.aedt.core.generic.file_utils import generate_unique_name, open_file

# 生成唯一名称
name = generate_unique_name("Setup")  # "Setup", "Setup_2", "Setup_3", ...

# 打开文件
with open_file("data.csv", "r") as f:
    content = f.read()
```

---

## AEDT 版本检查装饰器

```python
from ansys.aedt.core.internal.checks import min_aedt_version

@min_aedt_version("2023.2")
def my_function():
    # 只在 AEDT >= 2023 R2 时可用
    pass
```

---

## 设计管理（from ansys.aedt.core.application.design）

```python
# 基本设计操作
hfss.project_name      # 项目名
hfss.design_name       # 设计名
hfss.solution_type     # 解决方案类型
hfss.working_directory # 工作目录
hfss.project_file      # 项目文件路径

# 设计操作
hfss.save_project()
hfss.close_project(save=True)
hfss.duplicate_design("new_design")
hfss.set_active_design("new_design")
hfss.delete_design("old_design")

# 变体
hfss.available_variations.nominal_values
hfss.available_variations.nominal_variation()
```