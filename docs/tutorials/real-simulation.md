# 真机仿真：跑通第一个 openEMS 求解点

> 本文把"配方世界"接到"真电磁求解器世界"：环境自检 → 离线几何审计
> → 真跑一个点 → 读结果。以 openEMS 为主通道（开源、无 license 门槛），
> 全程代码实测过。前置：docs/tutorials/getting-started.md（已用 fake
> 适配器走通过全链路）。

## 1. 入口地图（先读，防撞墙）

rfauto 的仿真通道分两层，**openEMS 在两层的入口不一样**：

| 层 | 入口 | 支持的适配器 |
|---|---|---|
| 单跑面（run/tune 一次性执行） | `rfauto run <配方> --adapter <名>` | fake / hfss |
| 战役面（tune/sweep 真跑外环） | `optimization/adapter_channels` 通道注册表 | fake / hfss / openems |
| 直连面（Python API） | `OpenEMSSolver(EMSolverConfig(...))` | 全部 |

实测——单跑面目前**不认** openems：

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter openems --dry-run
```

实测输出（退出码 1）：

```
✗ dry-run 校验失败
  - 未知适配器: openems
```

`tune --adapter openems --dry-run` 同样被拒。想用 CLI 跑 openEMS
优化战役，去掉 `--dry-run` 走真跑路径（战役面的通道注册表含
openems）：

```python
from rfauto.optimization.adapter_channels import channel_names
channel_names()          # → ('fake', 'hfss', 'openems')
```

想精细控制单点求解（本文学的就是这条），用直连面。下面四节走
直连面，第 6 节给通道全景。

## 2. 环境自检（约 1 分钟）

```python
from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.em_solver_base import EMSolverConfig

print(resolve_openems_exe())
# → vendor/openEMS/install/bin/openEMS.exe（仓库相对路径；
#   解析顺序 configs/solvers.yaml → RFAUTO_OPENEMS_BIN 环境变量 → 兜底）

assert OpenEMSSolver(EMSolverConfig(
    solver_type="openems",
    exe_path=resolve_openems_exe())).connect()
```

connect() 通过即绑定在位。openEMS/CSXCAD 是源码编译绑定（无 PyPI
wheel），缺失时先读 docs/openems_build_guide.md。HFSS 与 ADS 通道
的环境探测用 `rfauto doctor`。

## 3. 真跑之前：离线几何审计（纪律位）

**先离线审计再真跑**是本项目铁律：字符串检查抓不住画法错误（历史上
"中心线弦"馈电、共线断口直通线都通过了语法检查），判据必须落在
CSXCAD 实测对象上。审计不经仿真、秒级完成：

```python
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

# mline 模板名义参数：{'w_mm': 1.113, 'line_len_mm': 40.0}
text = render_script("mline", dict(TEMPLATE_NOMINAL["mline"]),
                     (2.15, 2.65), mesh_resolution_mm=0.4)
head = text[:text.index("FDTD.Run(")]   # 截掉求解段，只留建模段
scope = {"__name__": "__main__", "__file__": "offline_audit.py"}
exec(compile(head, "offline_audit", "exec"), scope)
prims = scope["CSX"].GetAllPrimitives()
print("primitives:", len(prims))
```

实测输出：`primitives: 15`（15 个 CSPrimBox）。到这一步你手里已经有
真实的 CSXCAD 对象——原语是否零体积、端口激励体积是否非零、导体
连通性、网格最小间距，全部可以零仿真核对。全套判据的权威实现在
`tests/unit/_geometry_audit_helpers.py`（原语/端口/连通性/网格四类
门），每个模板的定向单测就是审计门槛。完整走法见
docs/how-to/run-openems-smoke.md。

## 4. 真跑一个点

求解骨架（`scripts/coupled_bpf_smoke.py` 的实际用法，模板与参数按你的
设计替换）：

```python
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.em_solver_base import EMSolverConfig

solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir="runs/my_first_run",        # 产物落这里
    freq_range_ghz=(2.15, 2.65),
    mesh_resolution_mm=0.4))
assert solver.connect()
assert solver.build_geometry(
    {"template": "mline", "params": {"w_mm": 1.113, "line_len_mm": 40.0}})
result = solver.solve()          # 时域 FDTD（长跑，见下方纪律）
assert result.success
f_ghz = result.freq_ghz          # 频轴（GHz）
s = result.s_params              # S 张量
solver.close()
```

**长跑纪律**：openEMS 全波求解常在分钟到小时级。超过 10 分钟的求解
用后台分离进程 + 日志文件轮询的方式跑（别在前台会话里干等），并且
注意同机并发真跑会互相拖慢 3–8 倍——计时敏感的求解串行跑。
`scripts/coupled_bpf_smoke.py` 展示了完整形态。

## 5. 读结果

求解产物落 run 目录，核心是 S 参数 csv（列语义：频率 + 每端口的
实部/虚部对）：

```
freq_hz,re_S11,im_S11,re_S21,im_S21,...
2300000000.0,0.0649,-0.1098,0.4440,-0.5664,...
```

两个要点：

1. **单激励文件是零填充部分矩阵**——非激励端的行列是补齐值不是
   测量值，消费时认掩码载体（csv + 掩码），别拿补齐值当证据。
2. 用体检门判读，别手算：

```bash
rfauto runs health <run_id>
```

用法与输出读法见入门教程第 6 节（docs/tutorials/getting-started.md）
与 docs/how-to/read-verdict-gates.md。

## 6. 多保真全景

rfauto 是多引擎架构，各通道分工：

| 通道 | 定位 | 门槛 |
|---|---|---|
| fake | 解析近似，链路冒烟 | 无 |
| openEMS | 开源 FDTD 全波 | 编译绑定 |
| HFSS（AEDT） | **对齐基准**，仲裁裁判 | 商业 license |
| ADS | 有源网表/谐波平衡 | 商业 license |

同模型的跨引擎差异不是噪声而是系统偏差——这正是"锚"登记的对象
（docs/tutorials/anchor-guide.md）。战役里可用 `--fidelity auto` 让
框架按保真阶梯调度。

## 7. 下一步

- 完整冒烟走法（判据门全流程）：docs/how-to/run-openems-smoke.md
- 编译安装 openEMS 绑定：docs/openems_build_guide.md
- 引擎系统偏差与锚：docs/tutorials/anchor-guide.md
- 归档判读的判据重放（这次判读今天还成立吗）：docs/tutorials/
  recast-walkthrough.md
- 给 rfauto 加一个新求解器：docs/tutorials/extending-rfauto.md
