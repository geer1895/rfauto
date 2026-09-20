# 端口设置模式（从 pyaedt 源码和测试提取）

## Wave Port 模式

### 模式 1：face_id + 自动积分线（推荐）
最可靠，让 pyaedt 自动选择积分线方向。

```python
faces = hfss.modeler.get_object_faces("trace")
port_face = min(faces, key=lambda f: hfss.modeler.get_face_center(f)[0])
port = hfss.wave_port(assignment=port_face, name="port1", impedance=50)
```

### 模式 2：axis_directions 指定方向
用预定义方向常量指定积分线方向。

```python
port = hfss.wave_port(
    assignment=rect_sheet,
    integration_line=hfss.axis_directions.XNeg,  # -X 方向
    impedance=50,
    name="port1",
)
```

### 模式 3：两点列表指定积分线
手动指定积分线起点和终点。

```python
port = hfss.wave_port(
    assignment=rect_sheet,
    integration_line=[[0, 0, 0], [0, 0, 0.508]],
    impedance=50,
    name="port1",
)
```

### 模式 4：微带线专用
自动扩展端口尺寸（vfactor × h）。

```python
port = hfss.wave_port(
    assignment=rect_sheet,
    is_microstrip=True,
    vfactor=3,  # 垂直扩展 3 倍基板厚度
    hfactor=5,  # 水平扩展 5 倍线宽
    impedance=50,
    name="ms_port",
)
```

### 模式 5：从两个对象创建
自动在两个对象之间创建端口。

```python
port = hfss.wave_port(
    assignment="ground_plane",
    reference="trace",
    integration_line=hfss.axis_directions.ZPos,
    impedance=50,
    name="port1",
)
```

## Lumped Port 模式

### 模式 1：对象名 + 参考对象
```python
port = hfss.lumped_port(
    assignment="trace",
    reference="ground",
    integration_line=hfss.axis_directions.ZPos,
    impedance=50,
    name="lumped_port",
)
```

### 模式 2：face_id
```python
face_id = hfss.modeler.get_object_faces("trace")[0]
port = hfss.lumped_port(
    assignment=face_id,
    impedance=50,
    name="lumped_port",
)
```

## 端口物理要点

### 微带线端口必须有空气域
```
错误：Port does not have a solved inside material on either side
原因：端口面没有接触基板（dielectric）材料
解决：添加空气域（vacuum box）覆盖整个结构 + 辐射边界
```

### 空气域尺寸
```python
# 空气域应覆盖整个结构，顶部留 5mm 以上
hfss.modeler.create_box(
    ["-pad", "-pad", "0"],
    ["l+2*pad", "2*pad+w", "h+t+5mm"],
    name="airbox", material="vacuum",
)
```

### 辐射边界
```python
# 赋在空气域顶面
air_faces = hfss.modeler.get_object_faces("airbox")
top_face = max(air_faces, key=lambda f: hfss.modeler.get_face_center(f)[2])
hfss.assign_radiation_boundary_to_faces(top_face)
```

## 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| Port does not have a solved inside material | 端口面没有接触基板 | 添加空气域 + 辐射边界 |
| both endpoints of port lines must lie on the port | 积分线端点不在端口面上 | 改用 face_id 让 pyaedt 自动选择 |
| length of port lines must be greater than zero | 积分线起点=终点 | 检查坐标，确保两点不同 |
| List of coordinates is not set correctly | 积分线格式错误 | 用 [[x1,y1,z1], [x2,y2,z2]] 格式 |

## 真机验证补充（Wilkinson 功分器全链路实测）

### ⚠ 模式 1（trace 端面 + is_microstrip）在本项目场景失效

`wave_port(assignment=<trace 端面 face_id>, is_microstrip=True, vfactor=3, hfactor=5)`
虽然能创建端口且求解"正常完成"，但产生**退化端口**：积分线长度 = 铜箔厚度（0.035mm），
物理结果为 S11≈0dB 全反射、S21≈-170dB 无传输（等效短路）。

### ✅ 实测可靠模式：显式端口 sheet（教科书式微带波端口）

```python
# XZ 面垂直矩形（法向 = 传输方向 Y），从接地面 z=0 延伸到 3*sub_h+铜厚，
# 宽度数倍线宽，sheet 允许穿过基板（标准做法）
sheet = modeler.create_rectangle(
    orientation=Plane.ZX,                      # width 沿 Z、height 沿 X
    origin=[f"({cx}-{w}/2)", y_port, "0mm"],
    sizes=["(sub_h+copper_t+3*sub_h)", w],
    name="PortSheetInput",
)
face = modeler.get_object_faces("PortSheetInput")[0]
hfss.wave_port(assignment=face, name="PortInput", impedance=50.0,
               renormalize=True, integration_line=Gravity.ZPos)  # 从地到信号
```

修复后真机指标：S11=-14.7dB, S21=-3.15dB, S32=-22.7dB（Wilkinson 2.4GHz）。

### ⚠ 波端口必须位于求解域外边界

端口 sheet 在空气域内部时报错：
`Waveport ... is internal to solution domain and not fully backed with a PEC object`。
修复：**基板/接地面/空气域在传输方向终止于端口平面**（不留空气边距），
即标准导波结构配置。pyaedt 只报 "Error in Solving"，真实错误在 AEDT 的
**batch.log**（工作目录下）——非图形模式调试必看。

### 其他实测要点

- `Plane.ZX` 的 sizes 顺序 = [Z 尺寸, X 尺寸]（cs_plane_to_axis_str：ZX 法向 Y）；
- 多端口并列时端口 sheet 宽度必须 < 相邻端口间距，否则 sheet 重叠导致求解失败；
- 空气域与基板体积重叠需显式 `modeler.subtract(AIRBOX, [SUBSTRATE, TRACE])`；
- 隔离电阻：垂直 sheet（XZ 面）边缘贴两臂内壁比水平贴底面接触可靠。
