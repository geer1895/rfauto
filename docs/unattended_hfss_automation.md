# 无人值守 HFSS 自动化：会话模式与批处理模式

> 状态：正式文档（2026-10-08 首版）。
> 定位：把本项目一年多真机踩坑经验中关于"无人值守跑 HFSS"的部分沉淀成
> 可执行的操作纪律。核心结论已在 Ansys Developer 社区分享并获 Ansys
> 团队成员确认（EDB/批处理路线的口径即来自该答疑）。
> 证据基线：pyaedt 1.4.0 × AEDT 2025 R1（v251），gRPC 非图形会话，
> Windows x64，商用许可。文内 `#NNN` 为本仓  坑号，逐条可溯源
> （对照表见文末附录）。
> 标注约定：未经本仓真机实测、只引自官方文档或社区答疑的口径，写
> "待验证"。

---

## 1. 两种模式

无人值守跑 HFSS 只有两种基本形态，其余都是它们的组合：

| | 长会话模式 | 批处理模式 |
|---|---|---|
| 形态 | 一个 Python 进程持有单个 AEDT Desktop（PyAEDT `Desktop`+`Hfss`），建模/求解/导出全在同一会话内反复进行 | 每个求解点起一个独立 `ansysedt` 进程（`-ng -BatchSolve`），进程退出后收产物，不驻留会话 |
| 单点开销 | 一次 Desktop 启动 + 一次工程打开，后续每点只付几何修改与求解时间 | 每点都付 AEDT 启动 + 工程装载成本 |
| 失败半径 | 一次失败赋值可毒化整个会话（§2），后续全部调用失败 | 无共享会话态可毒化；挂死最多拖死一个点 |
| 适用 | 优化内环反复改变量、交互式探索 | 无人值守战役、数据集生成、overnight 队列 |

### 1.1 长会话模式（PyAEDT Desktop+Hfss 单会话）

最小可用形态（真机实证口径）：

```python
from ansys.aedt.core import Desktop, Hfss

desktop = Desktop(version="2025.1", non_graphical=True, new_desktop=True)
hfss = Hfss(project="demo", design="demo")
try:
    ...  # 建模 → analyze_setup → 导出
finally:
    hfss.release_desktop(close_projects=True, close_desktop=True)
```

要点：

- `Desktop` 构造参数名是 `version=`/`non_graphical=`/`new_desktop=`
  （不是旧版 `specified_version`）。
- **唯一 Hfss 实例原则**（#191）：对同一 Desktop 建第二个 `Hfss` 实例，
  2025.1 下后建实例的设计变量管理器会失效——`GetVariables()` 返回
  `None`、`Rename` gRPC 失败（2023.1 无此问题，属版本漂移）。本仓
  `HfssSession.connect` 因此在 connect 阶段不再建占位 Hfss，唯一实例由
  adapter 按目标项目创建。
- 本仓载体是 `HfssSession` 单例（`src/rfauto/adapters/hfss_session.py`）：
  幂等 `connect`、license 指数退避重试（`Watchdog.license_backoff`）、
  `health_check()`（读 `desktop.current_version` 属性——不是
  `version_keys()`，后者不存在）、`reconnect_with_backoff`、`close` 统一
  释放。服务层走它；独立脚本可以按上面最小形态自管。
- 代价：所有调用共享一份会话状态。这是它的效率来源，也是 §2 整类故障
  的根源。

### 1.2 批处理模式（ansysedt -ng -BatchSolve，每求解一进程）

命令行口径（官方）：

```text
ansysedt -ng -BatchSolve <project>.aedt
ansysedt -ng -BatchSolve -Logfile solve.log <project>.aedb
```

- `-ng`：非图形；`-BatchSolve`：批求解。`-BatchSolve` 支持
  `design:setup` 限定只解某设计的某个 setup（官方文档口径；本仓未实测
  该限定的具体分隔语法——待验证）。
- `-Logfile <file>`：落 console log。**发射必带**：非图形会话里
  `GetMessages` 经常为空，console log 才是可靠的错误通道（真机两起
  建模错误全靠读 log 定位，见附录 #srv）。
- 工程参数：普通 `.aedt`；EDB 场景**直接指向 `*.aedb` 文件夹**——
  求解自动启动、`.aedt` 工程自动生成。这是 Ansys 团队成员在社区答疑中
  确认的口径（本仓 EDB 批处理原型尚未打通，端到端待验证，§4）。
- 注意不要与 `-grpcsrv`（gRPC 服务监听，供 PyAEDT 远程 attach）混淆：
  那是"驻留会话被人驱动"的形态，不是批求解。

适用与代价：

- 适合无人值守战役/数据集生成：每求解一进程是**结构性**的鲁棒性——
  没有可被毒化的共享会话（§2 整类故障不存在），一个点挂死看门击杀即止，
  不会无限期占许可席位。
- 代价：每点付启动成本；跨点状态只能落盘传递（工程文件或 §4 的 JSON
  仿真配置）。
- 本仓现状：现行无人值守仲裁/锚点脚本用"每点整轮新会话"（每点独立
  Python 子进程 + `new_desktop=True` + `finally` 必释放）近似同一哲学；
  EDB→`-BatchSolve` 直跑通路打通后应迁移（§4、§5.1）。

### 1.3 决策树

```text
这个求解点需要复用上一点的会话内状态吗？
（变量/边界/网格设置在点间逐步演化——典型的优化内环、交互式探索）
├─ 是 → 长会话模式
│        硬性配套：健康探针 + 毒化判 None（§3）+ 整轮重建钩子
│                   + 看门狗（§5.2）
│        毒化即弃：整个会话作废重建，绝不带毒续跑
└─ 否 → 进程隔离（每求解一进程）
         ├─ 平面/版图族，几何可由 EDB 表达
         │    → PyEDB 建库 + ansysedt -ng -BatchSolve 直指 *.aedb（§4）
         └─ 3D 参数化模板
              → 驱动脚本每点独立进程 + 独立会话（new_desktop，
                finally 必释放）；批处理直跑通路打通后迁 -BatchSolve
```

判据经验：**无人值守一律优先进程隔离**。长会话省下的启动成本，只有在
"人在旁边、失败能立刻人工接管"时才真的便宜；凌晨三点的战役里，它换来的
是 §2 那类整夜空转。

---

## 2. 会话污染案例研究：一次失败赋值带死整个会话

素材：`docs/upstream_issue_draft_pyaedt_wave_port.md`（已作为可复现
issue 提交 PyAEDT 上游，坑号 #413/#308），复现探针在
`runs/pyaedt_issue_probe/`，全部当日真机实测。

### 2.1 事故链

1. 多模波端口的 `integration_line` 有两种几乎同形的写法。文档口径是
   `[start_points_per_mode, end_points_per_mode]`（外层 2 元素，每元素
   每模一个点）；直觉写法是"每模一个 `[start, end]` 对"。
2. `wave_port()` 的形状检查（外层长度==2、内层等长列表）放过了后者，
   于是 `int_line_start = line1`、`int_line_stop = line2`——两条意图线
   共用原点时，模 1 的积分线变成 P0→P0，AEDT 拒绝赋值：

   ```text
   script macro error: port 'portwrongfmt': length of port lines must be greater than zero
   ```

3. 冒到用户代码的异常是泛化的
   `AEDTRuntimeError: Failed to create boundary Wave Port ...`——真实
   原因只在日志里（`PyAEDT ERROR: Last Electronics Desktop Message - ...`）。
4. **失败赋值之后**，同一会话的设计元数据查询面整体返 `None`（下节）。
   从这一刻起一切调用皆失败，脚本永远走不到 `release_desktop()`；
   无人值守下就是孤儿 `ansysedt.exe` 无客户端空挂、占着许可席位直到
   有人手工击杀（#265 实测占轨 5h）。
5. #308 补充观测：此类失败后 gRPC 通道一并损坏，`finally` 里的
   `release_desktop` 会**静默失败**——孤儿留下的路径不止一条。

新鲜会话上只跑文档形状的调用则完全正常，可排除"端口/几何本身非法"。

### 2.2 症状（同一会话，失败赋值前后实测）

| 查询 | 失败前 | 失败后 |
|---|---|---|
| `hfss.oboundary.GetBoundaries()` | `[]` | `None` |
| `hfss.odesign.GetVariables()` | `[]` | `None` |
| 迭代 `hfss.boundaries` | 正常 | `TypeError: 'NoneType' object is not iterable` |
| 第二次 `wave_port()`（文档形状） | — | `AttributeError: type object 'hfssconstants' has no attribute 'default_solution'` |
| `modeler.create_rectangle(...)` | 正常 | 变量管理器内 `TypeError` |

`solution_type` 级联：`DesignSolutions.solution_type` 读
`GetSolutionType()`（此时返 `None`），`"Modal" in None` 的 `TypeError`
被 `except` 吞掉，兜底 `self._design_type.default_solution` 在 1.4.0
上不存在——于是抛 `AttributeError`。这个"第二跳异常"极具迷惑性：它
看起来像 pyaedt 的 bug，实际是第一跳失败赋值的余波。

### 2.3 诊断三探针

写任何长会话驱动代码时，把这三个探针做成廉价函数，在关键节点前后调用：

```python
def session_health(desktop, hfss) -> str:
    """返回 "ok" / "poisoned" / "dead"。

    desktop = Desktop 实例，hfss = Hfss 应用实例。
    None 判毒化的依据见 §2.2。
    """
    try:
        v = desktop.current_version              # 探针1：传输/进程活性
        if not v or not str(v).strip():
            return "dead"
    except Exception:
        return "dead"
    try:
        if hfss.oboundary.GetBoundaries() is None:  # 探针2：边界查询面
            return "poisoned"
        if hfss.odesign.GetVariables() is None:     # 探针3：变量查询面
            return "poisoned"
    except Exception:
        return "poisoned"
    return "ok"
```

判读契约：

- 健康会话上 `GetBoundaries()`/`GetVariables()` 返回**列表**（空设计
  就是 `[]`）；返回 **`None` 即判毒化**。契约是"None ≠ 空"，不是
  "非空 = 健康"。
- `current_version` 异常或为空 = 会话已死（进程没了或 gRPC 断了）。
- 已知第二根因：`GetVariables()` 返 `None` 也可能是同桌面双 `Hfss`
  实例（#191）。探针只能告诉你"会话病了"，不能告诉你哪种病——但处置
  相同：弃会话重建。不要在毒化会话上做归因实验。

### 2.4 处置原则：fail-fast + 重建

- **绝不带毒续跑**。毒化后任何"再试一次""跳过这步"都是往夜里扔时间：
  后续每一步都会以新形态失败，最后连清理路径都走不完。
- 检测到 `poisoned`/`dead`：立刻放弃当前会话对象，把本求解点记为失败
  （附最后一次真实的 AEDT 错误消息，见 §3.4），在**新进程**里重建会话
  重试该点（整轮重建，不是会话内修复）。
- 重建前先做孤儿清场（§5.4）：毒化会话大概率已留下孤儿 `ansysedt`，
  不清场则重建会 attach 到残留实例或直接耗尽许可席位。
- 释放路径自身要防御：`release_desktop` 包 150s 上限（§5.3），失败与
  超时都只记日志交人工核对，不让清理代码把主流程拖死。

### 2.5 为什么无人值守下这一类最致命

- 有人的时候，第一跳的泛化异常一个下午能调试出来；无人值守时 agent/
  脚本只会看到一个 `AttributeError`，直接失败，且**后续队列里每个点都
  陪葬**（共享会话）。
- 这一类故障是我们一年无人值守实战中最大的实际障碍——同样的结论写进了
  Ansys Developer 社区分享帖。批处理模式（§1.2/§4）之所以值得每点多付
  启动成本，就是因为它从结构上消灭了这一类。

---

## 3. 健康检查与失败恢复

### 3.1 调用前探针

- 连接面：`desktop.current_version` 非空即认为传输与进程存活（本仓
  `HfssSession.health_check` 的口径；`version_keys()` 不存在，别用）。
- 业务面：进入"建模→求解→导出"主序列前跑一次 §2.3 三探针；长会话里
  每个求解点开始前再跑一次。探针是亚毫秒级元数据查询，不值得省。
- 环境/许可面：发射前先确认安装与许可可达（`RFAUTO_AEDT_PATH`、
  `RFAUTO_LICENSE_SERVER` 探测），连接阶段 license 错误按指数退避重试
  数次再判死（本仓缺省 3 次，`Watchdog.license_backoff`）。

### 3.2 毒化判 None

- 契约只有一条：**元数据查询返回 `None` = 会话毒化**。`[]` 是健康的空，
  `None` 是病。
- `hfss.boundaries` 迭代抛 `TypeError: 'NoneType' object is not
  iterable`、建模操作死在变量管理器里，都是同一毒化态的二级症状；
  抓到任何一个都按毒化处置，不必再收集证据。
- 把判 None 写在服务层单一函数里（参照 §2.3），调用方只认三种返回值。

### 3.3 重建钩子

- 重建单位是**整轮**：新进程、新 Desktop、新 Hfss，从建模重跑该点。
  本仓无人值守脚本的惯例是 `BUILD_ATTEMPTS = 2`（整轮重建重试 ≤2），
  重试轮之间做孤儿清场（§5.4）。
- 重试轮内建会话用 `new_desktop=True` 起新实例；不要 `attach` 到上一轮
  的残留——你无法证明残留实例没有毒。
- 每轮结束（无论成败）在 `finally` 里落盘"求解记录"（该点参数、耗时、
  错误消息、产物路径），再进入清理。战役级重启后能凭记录续跑，不重跑
  已成功的点。

### 3.4 错误消息透出（best-effort）

- AEDT 的真实错误（如 `length of port lines must be greater than
  zero`）只出现在 pyaedt 日志行 `PyAEDT ERROR: Last Electronics Desktop
  Message - [error] ...`，冒到 Python 的异常是泛化文案。**把日志里的
  Last Electronics Desktop Message 抓出来附进自己的异常/记录**，是
  无人值守排障时性价比最高的一件事——最佳努力即可（读不到就记
  "unknown"，不阻塞主路径）。
- 不要依赖 `GetMessages`：非图形会话下它经常为空（真机两起建模错误
  都是靠 `-Logfile` console log 定位的，附录 #srv）。批处理模式因此
  发射必带 `-Logfile`。
- 长跑 Python 驱动一律 `-u`（unbuffered）+ 落盘日志：重定向管道的缓冲
  会让日志迟迟不落地，看着像挂死。

### 3.5 求解真伪复核（API 返回值 ≠ 引擎完成）

- pyaedt 的 `analyze_setup` 会吞引擎异常并无条件打 "solved correctly"
  类日志；返回 `True` 不等于引擎层完成。导出前必须复核：
  - profile 状态无引擎错误关键字（本仓 `_profile_status` +
    `_PROFILE_FAILURE_KEYWORDS`；真机 4-7s 的静默失败只在此显形）；
  - sweep 完成断言（本仓 `assert_sweep_completed`：setup 有求解
    profile、`is_solved` 为真，否则拒绝导出）。
- 复核失败按"该点失败"记录，**不要**把半成品数据写进数据集——健康门
  的 FAIL 也比脏数据便宜。

---

## 4. EDB 快车道（PyEDB + 批处理直跑）

适用对象：平面/版图族器件（耦合器、功分器、滤波器版图实现、封装
RDL/过孔阵列），以及一切"几何可由版图数据库表达"的数据集生成。

### 4.1 PyEDB 是独立的内存态 API

- `pyedb`（PyAnsys 生态）直接操作 EDB/AEDB 数据库：**无需桌面会话**，
  进程内内存态读写；但**需要本机有合法许可的 AEDT 安装**（官方 README
  口径；我们据此确认本仓可用）。官方对它的定位包含 "completely
  non-graphical flows, from layout translation through simulation
  results"。
- 本仓环境实测安装版本：pyedb 0.83.0（下述 API 名逐字核对自该安装包
  源码）。

```python
from ansys.aedt.core import Edb   # 工厂函数，惰性导入，返回 pyedb.Edb

edb = Edb(r"E:\runs\branchline.aedb", version="2025.1")
#   叠层/连线/过孔/端口等版图操作 ...
edb.save()
edb.close()
```

- `edbpath` 指向 `.aedb` **文件夹**（EDB 是文件夹型数据库）；
  `Edb()` 是工厂函数。其余构造参数（cellname/isreadonly/
  technology_file 等）以当版文档为准——待验证。

### 4.2 JSON 仿真配置：edb.configuration.load / export

pyedb 内置声明式仿真配置（`Configuration` 对象，`edb.configuration`
属性暴露，dotnet/grpc 两后端一致）：

```python
edb.configuration.load(r"E:\runs\branchline_sim_config.json")   # 应用配置
edb.configuration.export(r"E:\runs\branchline_sim_config.json") # 导出配置
```

- `load(config_file, ...)` / `export(file_path, ...)`；导出覆盖面
  （setups/ports/boundaries/stackup/variables/...）由关键字参数逐项
  控制（缺省大多为 True）——细节以当版 docstring 为准。
- 对配方驱动架构的意义：器件模板可以在产几何的同时**产出一份 JSON
  仿真配置**，批处理一步保持全声明式——参数到求解之间没有任何脚本化
  手感环节。这是该 API 对我们最干净的契合点（Ansys 团队成员在社区
  答疑中主动指出的方向）。

### 4.3 批处理命令行直接消费 aedb 文件夹

- 建好 ready-to-solve 的 EDB 后，AEDT 批处理命令行与普通工程同款，
  路径指向 `*.aedb` 文件夹而非 `.aedt` 文件即可：求解自动启动、
  `.aedt` 工程自动生成（Ansys 团队成员确认的口径）。
- 于是无人值守形态收敛为：**PyEDB 建库（无桌面会话）→ `ansysedt -ng
  -BatchSolve -Logfile ... <点>.aedb`（每求解一进程）→ 收 Touchstone**。
  全链没有长驻会话，§2 的故障类无处附着。
- 本仓状态：branchline/功分器两模板的原型在计划中（建库→批解→与既有
  HFSS 3D 通路对拍，HFSS 为对齐基准），端到端时序与产物形态**待验证**；
  打通前，§1.2 的"每点整轮新会话"仍是现行无人值守通路。

### 4.4 适用与不适用

- 适用：平面族数据集批量生成（桌面会话恰是这些场景的瓶颈与脆弱点）、
  封装/版图侧 SI/PI 分析的入口。
- 不适用（现阶段）：全空气盒的三维辐射结构（天线等）——几何是参数
  驱动在 HFSS 3D 原生建的，EDB 不替代该主路径；这类保持 §1.1/§1.2。

---

## 5. 进程隔离与看门

### 5.1 每求解一进程（openEMS 先例与 HFSS 的统一）

- openEMS 侧既有先例：多端口全 S 矩阵按激励拆成 N 个子进程
  （`excite_port` 参数化 ×N 子进程，`openems_rotation.py`），进程内对象复用
  被明确禁用（#208：`Run(cleanup=True)` 会销毁 C++ 对象）——教训是
  **跨求解复用进程内状态，失败模式又隐蔽又难清**。
- HFSS 批处理把同一哲学下沉到 `ansysedt` 进程级：每求解一进程，进程
  退出即回收一切。两引擎在战役 runner 层面统一为同一种调度形态：
  点队列 → 子进程 → 产物 → 下一点。
- 并发发射池也按进程组织：单席崩溃/挂死不连坐其他席（#157 家族教训）；
  计时/判读进程不与求解争同一解释器（GIL）。
- 进程内 openEMS 形态（python 进程内 `FDTD.Run`）的互斥识别另有口径
  （按命令行匹配 runner 脚本名，不是找 `openEMS.exe`），移植到 HFSS 时
  注意 `ansysedt.exe` 才是进程面。

### 5.2 看门狗：超时必须配合"真打断"判据

长会话模式下求解调用是阻塞的，看门狗只能从监控线程/进程触发。本仓
`Watchdog`（`src/rfauto/pipeline/watchdog.py`，`threading.Timer` 封装）
在 `HfssAdapter.solve` 的用法是标准答案：

```python
watchdog = Watchdog()
aborted = False

def _abort_on_timeout():
    nonlocal aborted
    odesign = getattr(hfss, "odesign", None)
    if odesign is not None:
        odesign.Abort()          # COM/gRPC 层中止当前 setup 求解
        aborted = True

watchdog.start(timeout_s=timeout_s, callback=_abort_on_timeout)
try:
    success = hfss.analyze_setup(name=setup_name, blocking=True)
finally:
    watchdog.cancel()
# 竞态保护：watchdog.fired 且 aborted 才判超时失败；
# fired 但求解已自行完成 → 接受真实结果，只提示调大超时
```

- **竞态保护是血泪条款**（#145）：到点但 `Abort` 失败说明求解实际已
  正常返回——曾把一个 93 分钟的正确求解当超时扔掉。只有真打断才判废。
- 超时值从**实测求解时间**定，不拍脑袋：网格/机器争用会放大数倍
  （单 setup 实测 4h59m 的先例，80 分钟级看门狗必误杀）。本仓环境变量
  `RFAUTO_HFSS_SOLVE_TIMEOUT_S` 统一覆盖单解超时。
- 批处理模式下同一逻辑更简单：子进程 `join(timeout)` 到点即杀进程树
  （杀前核对命令行，§5.4）。
- 进程存活判读别用 mtime 停走当卡死证据：stdio 缓冲会让产物文件 mtime
  长时间不更新（#268），看 CPU 占用 + 产物内时间轴增长才作数。

### 5.3 释放路径：release_desktop 必须带上限

- `release_desktop` 对**仍在求解中**的桌面会阻塞到求解自然结束——实测
  一次阻塞 3.6 小时。无人值守里这等于把"超时击杀"变成"超时空等"。
- 纪律：`finally` 里必释放（#265），但释放调用包 150s 上限
  （`desktop_guard.release_desktop_capped`）：超时不候，如实记"孤儿
  风险，待人工核对"，继续走收尾。

### 5.4 孤儿进程与许可席位（进程治理纪律）

孤儿 `ansysedt`（父进程已死、无客户端）会无限期占用许可席位。治理
单源在 `src/rfauto/infra/desktop_guard.py`，脚本一律委托它，纪律四条：

1. **杀前核对命令行**：枚举必须拿到 `pid/ppid/CommandLine`（PowerShell
   `Get-CimInstance Win32_Process`），枚举失败/不可解析=不杀
   （fail-closed，#245）。
2. **只杀孤儿**：父进程存活=活桌面，绝不代杀（可能是并行轨的合法桌面，
   #265 族连坐教训）；父进程已死=孤儿，点杀该 PID。
3. **杀后复核**：留退出窗再枚举，确认清场后才允许开新会话；未清场则
   fail-closed 不开新点。
4. 两档严格度：发射前/重试轮内 `strict=True`（任何异常即抛，宁可不开
   工）；收尾扫尾 `strict=False`（只记录不抛，收尾绝不连坐已完成的
   战役）。

shell 细节（Windows 实测）：git-bash 下 `taskkill /PID` 的 `/PID` 会被
MSYS 路径转换吃掉（静默不杀）——用 `//PID` 或 PowerShell
`Stop-Process -Id`；PowerShell 子进程调用一律带 timeout（枚举 30s/
存活 15s/点杀 60s），否则杀环自身可能无限挂起。

发射形态（远程/服务器侧尤其）：

- 用 console 可见的 bat 直指形态，**不用** schtasks 隐藏标志/wscript
  静默/`-WindowStyle Hidden`——这类隐蔽进程易被服务器杀毒静默击杀
  （#157 家族"整树无声消失"嫌疑面），且 bat 必带 `-Logfile`。
- 发射后必须做存活复核：console log 有公告 + CPU/工作集增长探针，
  确认真跑起来了再离开。

---

## 6. 无人值守战役发射前十条自查

1. **模式选对**：逐点无共享状态 → 进程隔离（批处理或每点新会话）；
   优化内环 → 长会话 + 全套 §3 配套。无人值守默认前者。
2. **探针就位**：会话驱动里有 §2.3 三探针；每个求解点开始前跑一次；
   返回 `None` 即弃会话重建。
3. **看门就位**：每个求解/每个阻塞调用都有超时；`RFAUTO_HFSS_SOLVE_TIMEOUT_S`
   按**实测**求解时间放大定值（非预算门，是防挂死上限）；超时判据走
   "真打断才算废"（§5.2）。
4. **释放带上限**：`finally` 必释放，`release_desktop` 包 150s 上限，
   超时记孤儿风险不空等（§5.3）。
5. **日志落盘**：批处理发射必带 `-Logfile`；Python 驱动 `-u` + 日志
   文件；`Last Electronics Desktop Message` 最佳努力附进失败记录；
   不依赖 `GetMessages`。
6. **孤儿清场**：发射前 `kill_orphan_ansysedt_desktops(strict=True)`
   fail-closed 预检；重试轮间与收尾按两档严格度复用（§5.4）。
7. **许可与版本预检**：安装路径（`RFAUTO_AEDT_PATH`）与许可可达性先探
   后跑；远程机器 AEDT 版本必须与本机 pyaedt 配对版本一致（版本配对
   断言，不一致拒连）。
8. **绝对路径**：工程/outdir/日志一律绝对路径——相对 `-outdir` 会让
   构造期 `Project.Rename` 挂起数分钟后报错（#243 实测）；临时目录放
   数据盘约定位置。
9. **结果复核独立于 API 返回值**：profile 状态/sweep 完成/`is_solved`
   断言过了才算数；复核失败该点记 FAIL，不把半成品写进数据集（§3.5）。
10. **逐点留痕 + 可续跑**：每点结束落"求解记录"（参数/耗时/错误消息/
    产物路径）；战役重启凭记录跳过已成功点；任务毕清进程、清临时目录。

---

## 附录：事实来源与坑号对照

| 文中主张 | 来源 |
|---|---|
| 会话污染全链（integration_line 误形、`[]`→`None`、`default_solution` 级联、gRPC 通道损坏） | `docs/upstream_issue_draft_pyaedt_wave_port.md`；`runs/pyaedt_issue_probe/`（pyaedt 1.4.0 + AEDT 2025 R1 真机实测）； #413/#308 |
| EDB 无会话/内存态/需本机 AEDT 许可；`-BatchSolve` 直指 `*.aedb`；JSON 仿真配置方向 | Ansys Developer 社区答疑（Ansys 团队成员）与本仓核实批账：`docs/ansys_dev_forum_post_draft.md` 回复草稿 1–3 |
| `Edb()` 工厂、`edb.configuration.load/export` 方法名与关键字 | 本仓 pyedb 0.83.0 安装包源码逐字核对（`pyedb/configuration/configuration.py`、`pyedb/dotnet/edb.py`、`pyedb/grpc/edb.py`） |
| `-Logfile` 纪律、GetMessages 常空、发射存活复核、隐蔽进程被杀毒击杀 | `docs/audit/server_invocation_playbook.md`；项目规则 规则 0b-2 |
| `ansysedt` 进程治理（枚举/只杀孤儿/复核/两档严格度、150s 释放上限、3.6h 阻塞实测） | `src/rfauto/infra/desktop_guard.py`（#245/#265/#105） |
| watchdog + `odesign.Abort()` + 竞态保护、`RFAUTO_HFSS_SOLVE_TIMEOUT_S`、profile/sweep 复核 | `src/rfauto/adapters/hfss_adapter.py`；`src/rfauto/pipeline/watchdog.py`；#145/#191 |
| `HfssSession` 单例行为（幂等 connect、license 退避、`current_version` 健康检查、唯一 Hfss 实例） | `src/rfauto/adapters/hfss_session.py`；#191 |
| 相对 `-outdir` 挂起 | 项目规则（df5 批 ②，#243） |
| openEMS 每求解一进程先例 |  #208、#261；`docs/audit/server_invocation_playbook.md` §2.5 |

> 维护约定：本文只沉淀"操作纪律 + 已验证事实"。新增坑例时按节归入，
> 并在附录表加一行来源；未实测的新口径先标"待验证"，真机闭环后回填。
