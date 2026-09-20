"""PyAEDT HFSS Examples — 从官方测试提取的示例代码。

用法：
    直接运行或复制到 rfauto 项目中使用。
    需要 AEDT license。
"""

# ─────────────────────────────────────────────────────────────────────────────
# 1. 基本连接 + 建模
# ─────────────────────────────────────────────────────────────────────────────

from ansys.aedt.core import Hfss
from ansys.aedt.core.generic.constants import Axis, Plane

hfss = Hfss(
    project="my_project",
    design="my_design",
    solution_type="DrivenModal",
    version="2025.1",  # 或 "2023.1"
    new_desktop=True,
)

# 创建盒子
box = hfss.modeler.create_box(
    origin=[0, 0, 0],
    sizes=[10, 5, 20],
    name="my_box",
    material="copper",
)

# 创建圆柱
cyl = hfss.modeler.create_cylinder(
    orientation=Axis.Z,
    center=[0, 0, 0],
    radius=3,
    height=80,
    name="inner_conductor",
    material="copper",
)

# 创建矩形（用于端口面）
rect = hfss.modeler.create_rectangle(
    orientation=Plane.YZ,  # YZ 平面
    origin=[0, -5, 0],
    sizes=[10, 5],
    name="port_sheet",
)

# 创建圆（用于端口面）
circle = hfss.modeler.create_circle(
    orientation=Plane.YZ,
    center=[0, 0, 0],
    radius=10,
    name="wave_port_sheet",
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. 微带线端口设置（推荐模式）
# ─────────────────────────────────────────────────────────────────────────────

# 方法 A：传 face_id，让 pyaedt 自动选择积分线（最可靠）
faces = hfss.modeler.get_object_faces("trace")
port_face = None
for f in faces:
    c = hfss.modeler.get_face_center(f)
    if abs(c[0]) < 0.01:  # 找 x=0 的面
        port_face = f
        break

port = hfss.wave_port(
    assignment=port_face,
    name="port1",
    impedance=50,
    renormalize=True,
)

# 方法 B：用 axis_directions 指定积分线方向
port = hfss.wave_port(
    assignment=rect,
    integration_line=hfss.axis_directions.XNeg,
    modes=1,
    impedance=50,
    name="port1",
    renormalize=True,
)

# 方法 C：用两点列表指定积分线
port = hfss.wave_port(
    assignment=rect,
    integration_line=[[0, 0, 0], [0, 0, 0.508]],
    impedance=50,
    name="port1",
)

# 方法 D：微带线专用（自动扩展端口尺寸）
port = hfss.wave_port(
    assignment=rect,
    is_microstrip=True,
    vfactor=3,  # 垂直扩展 3 倍基板厚度
    hfactor=5,  # 水平扩展 5 倍线宽
    impedance=50,
    name="microstrip_port",
)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Lumped Port
# ─────────────────────────────────────────────────────────────────────────────

# 创建两个盒子作为端口参考
box1 = hfss.modeler.create_box([0, 0, 50], [10, 10, 5], "BoxLumped1", "copper")
box2 = hfss.modeler.create_box([0, 0, 60], [10, 10, 5], "BoxLumped2", "copper")

port = hfss.lumped_port(
    assignment="BoxLumped1",
    reference="BoxLumped2",
    integration_line=hfss.axis_directions.XNeg,
    impedance=50,
    name="LumpedPort",
    renormalize=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Setup + Sweep
# ─────────────────────────────────────────────────────────────────────────────

# 创建 Setup
setup = hfss.create_setup(
    name="main_setup",
    setup_type="HFSSDriven",  # 或不传，用默认
    Frequency="2.4GHz",
    MaximumPasses=15,
    DeltaS=0.02,
)

# 或者用 kwargs
setup = hfss.create_setup(name="main_setup")
setup.props["Frequency"] = "2.4GHz"
setup.props["MaximumPasses"] = 15
setup.props["DeltaS"] = 0.02
setup.update()

# 创建频率扫描
hfss.create_linear_count_sweep(
    setup="main_setup",
    unit="GHz",
    start_frequency=1.0,
    stop_frequency=4.0,
    num_of_freq_points=201,
    name="sweep_1_4GHz",
    save_fields=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# 5. 求解 + 导出
# ─────────────────────────────────────────────────────────────────────────────

# 求解前设置自动导出（防 gRPC 断连）
hfss.export_touchstone_on_completion(export=True, output_dir=".")

# 求解
hfss.analyze(setup="main_setup")

# 手动导出（如果 gRPC 没断）
s2p_path = hfss.export_touchstone(
    setup="main_setup",
    sweep="sweep_1_4GHz",
    output_file="my_results.s2p",
)

# 保存项目
hfss.save_project()

# ─────────────────────────────────────────────────────────────────────────────
# 6. 微带线完整示例
# ─────────────────────────────────────────────────────────────────────────────

from ansys.aedt.core import Hfss  # noqa: E402  示例 2：各示例自含导入

hfss = Hfss(
    project="microstrip_example",
    design="ms_line",
    solution_type="DrivenModal",
    version="2025.1",
    new_desktop=True,
)

# 变量
hfss["w"] = "1.1mm"
hfss["l"] = "20mm"
hfss["h"] = "0.508mm"
hfss["t"] = "0.035mm"
hfss["pad"] = "5mm"

# 基板
hfss.modeler.create_box(
    ["-pad", "-pad", "0"], ["l+2*pad", "2*pad+w", "h"],
    name="substrate", material="Rogers RO4350 (tm)")

# 接地平面
hfss.modeler.create_box(
    ["-pad", "-pad", "0"], ["l+2*pad", "2*pad+w", "0mm"],
    name="ground", material="pec")

# 微带线
hfss.modeler.create_box(
    ["0", "-w/2", "h"], ["l", "w", "t"],
    name="trace", material="pec")

# 空气域（必须！）
hfss.modeler.create_box(
    ["-pad", "-pad", "0"], ["l+2*pad", "2*pad+w", "h+t+5mm"],
    name="airbox", material="vacuum")

# 辐射边界
air_faces = hfss.modeler.get_object_faces("airbox")
top_face = max(air_faces, key=lambda f: hfss.modeler.get_face_center(f)[2])
hfss.assign_radiation_boundary_to_faces(top_face)

# 端口
faces = hfss.modeler.get_object_faces("trace")
p1 = min(faces, key=lambda f: hfss.modeler.get_face_center(f)[0])
p2 = max(faces, key=lambda f: hfss.modeler.get_face_center(f)[0])

hfss.wave_port(assignment=p1, name="port1", impedance=50, renormalize=True)
hfss.wave_port(assignment=p2, name="port2", impedance=50, renormalize=True)

# Setup + Sweep
setup = hfss.create_setup(name="main_setup")
setup.props["Frequency"] = "2.4GHz"
setup.props["MaximumPasses"] = 15
setup.props["DeltaS"] = 0.02
setup.update()

hfss.create_linear_count_sweep(
    setup="main_setup", unit="GHz",
    start_frequency=1.0, stop_frequency=4.0, num_of_freq_points=201,
    name="sweep_1_4GHz", save_fields=False,
)

# 导出 + 求解
hfss.export_touchstone_on_completion(export=True)
hfss.analyze(setup="main_setup")
hfss.save_project()
hfss.release_desktop()
