# 解释：rfauto 的分层架构

> 这是一篇 explanation（解释文）：回答"为什么这样设计"，不教操作。
> 操作看 docs/tutorials/ 与 docs/how-to/，接口出处看 docs/reference.md。

## 分层图

```
cli/  mcp_server/  ui/            ← 壳：参数解析与渲染，零业务逻辑
        │
      service/                    ← 门面：JSON 进出、编排、判读
        │
linkage/ optimization/ models/    ← 领域：优化外环、跨工具联动、模型注册
        │
      adapters/                   ← 契约：EMSolverAdapter/Registry 等
        │
      pipeline/                   ← 流程：build → solve → post
        │
      infra/                      ← 基础设施：配置、run 存储、缓存
        │
      core/                       ← 内核：纯函数、确定性、零 IO
```

依赖只能自上而下：cli/mcp_server → service → linkage/optimization/models
→ adapters → pipeline → infra → core。这不是口头约定——**import-linter
强制**（契约见仓根 `.importlinter`，依赖声明见 pyproject dev 组），反向
import 直接红。

> UI 壳的内部形态（routes 分域/事件总线/前端 ESM 模块）见下文
> 「UI 架构」节——分层位置不变（仍是 service 之上的薄壳），只是壳内
> 有了自己的结构。

## 为什么 service 层是"JSON 进出"

CLI、MCP server、UI 三种壳共享同一业务，唯一可行的共享点是"参数进、
JSON 出"的门面函数。规则：

- **新功能先写 service 函数**，壳层只做参数解析、调用、渲染（薄壳零
  逻辑）。你在 `rfauto calc run` 里看不到一行公式，它只是
  `service.calculator_service.run_calculator` 的渲染器；
- 错误语义统一：`ok=False + error` 而非异常穿透到壳——脚本消费者靠
  退出码判成败，不必解析异构输出。

## UI 架构：双 HTTP 面、routes 分域与统一事件流

UI 壳曾长期是 `ui/server.py` 单体（全部 handler 挤一个文件）加前端
`pages.js` 单体。两轮重构后是"**装配薄壳 +
分域路由 + 一条事件总线 + 零构建前端 ESM**"的形态（下列数字
2026-10-14 树面实测）。

### 双 HTTP 面（同一 service 层，两个消费方各选各的面）

| 面 | 入口 | 前缀/端口 | 消费方 |
|---|---|---|---|
| 人工工作台 | `ui/server.py`（装配）+ `ui/routes/`（分域路由） | `/api/*`，loopback 8642 | 浏览器 |
| 程序化 REST | `service/rest_api.py` | `/api/v1/*`（OpenAPI 3.0.3），8644 | 脚本/第三方 |

两边各自独立路由表，新增能力按消费方选面，不在两边互相转发。
`ui/server.py` 只保留 app 装配（`create_ui_app`/CSP 中间件/Mount/serve
启动），全部 API handler 按域机械拆进 `ui/routes/`；route 表 66 条
`/api/*` Route + `/` index + `/static`、可选 `/runs` 两个 Mount。
参数守卫单源在 `ui/params.py`，CSP 策略单源在 `ui/csp.py`。

### routes 分域表（`ui/routes/`，10 业务域 + 事件面）

| 域模块 | Route 数 | 职责 |
|---|---|---|
| runs.py | 6 | run 清单/详情/双 run 对比/SSE 桥/run 执行/报告图片 |
| recipes.py | 5 | 配方视图/保存/清单、模型 3D 预览、文件浏览 |
| tune.py | 3 | 调参（后台线程启动/状态/trials；事件发布源） |
| agent.py | 12 | LLM 对话、沙箱草稿、审批收件箱、求解器注册表 |
| importer.py | 1 | HFSS 工程导入（.aedt → 设计规格 + 配方草稿） |
| measurement.py | 9 | 校准工作台/跨保真/S 参数/Smith 圆图/报告中心 |
| insight.py | 7 | 优化洞察（Pareto/可行性）/执行看板/成本时间线 |
| fieldviz.py | 4 | 远场极坐标/场可视化（nf2ff + DumpHDF5） |
| data.py | 6 | 数据集/标定锚/UQ |
| tools.py | 7 | 计算器/模板画廊/代理 Playground/剖析 |
| events.py | 3 | 统一事件流 SSE 端点（全域/tune 域/campaign 域） |
| campaign_app.py + edb_app.py（ui/ 顶层收编） | 3 | 战役看板 + EDB 快车道状态 |

分域纪律与端点清单的权威出处是 `ui/routes/__init__.py` 与各模块
docstring（本文只给结构，不复制清单——清单会烂，指针不会）。

### 统一事件流（`ui/routes/event_bus.py`）

实时面曾是三套语义并存（runs 的 SSE 桥、tune 轮询、campaign 队列
轮询）。事件总线把"进程内事件"收编为**一条**总线：统一信封
`{seq, ts, kind, domain, payload}`——seq 单调轴兼作 SSE `id:` 帧
（浏览器 EventSource 断线携 Last-Event-ID 即可续传）；环形缓冲
（缺省 512 条）做背压（慢客户端不阻塞发布方）；去重窗防多客户端
并发时重复发布；订阅数上限防连接泄漏。既有轮询端点零改动保留。

```
routes/tune.py ──状态转移/trial 探针──┐
routes/runs.py ──events.jsonl 桥懒镜像─┤→ EventBus（环形缓冲+去重窗+seq 轴）
routes/events.py ─campaign tick 差分──┘        │
                                               ▼ SSE 帧 event/id/data + 控制帧 hello/resync/end
                        前端 EventSource（pages/sse.js）→ 幂等整页刷新/增量更新
```

### 前端（`ui/static/`，零构建原生 ESM）

`app.js`（外壳：导航/3D/工具函数）+ `pages.js`（薄入口：视图注册表
组装 + 既有公开导出面 re-export）+ `pages/` **33 个模块**
（23 个 `view_*.js` 视图 + 10 个基础设施模块）。页面代码零构建——
原生 `<script type="module">` 相对路径 import，浏览器直跑；数据解释
逻辑全在 service 层，前端只渲染。

| pages/ 基础设施（10） | 职责 |
|---|---|
| context.js / router.js | 视图状态单源 / 两级 hash 路由 + VIEWS 注册表分发 |
| polling.js / sse.js | 可见性节流轮询 / EventSource 订阅与恢复 |
| charts.js / dom.js / kit.js | 图表导出与主题刷新 / DOM helper / 通用 UI 件 |
| sortable.js / filebrowser.js | 可排序表格 / 文件浏览 |
| dashboard_util.js | 总览 widget 注册表工具 |

23 个 `view_*.js` 与工作台页面一一对应（dashboard/runs/detail/recipe/
tune/campaign/queue/loopboard/optstack/timeline/calibration/sparams/
fieldviz/gallery/tools/playground/profile/data/import/agent/reports/
solvers/guide），逐模块职责见各自文件头注释。

给贡献者的推论照旧：路由是薄壳（守卫单源 + service 调用 + 信封
构造），新页面先 service 端点再 `view_*.js` 渲染层；程序化消费走
`/api/v1`（`rfauto rest schema` 机读清单，25 端点实测），别往工作台
面挂机器接口。

## 为什么数值只在确定性内核（core）

rfauto 的领域是射频仿真自动化，一条铁律支配整个架构：**LLM/agent 永远
不产生物理数字**。频率/损耗/几何数值只由确定性求解器、综合引擎或评判
器产出；agent 只产出 typed tool call（可复现、模型无关）。因此：

- core 层纯函数（如 `core/cascade.py`、`core/wcd.py`）零 IO、零随机性
  （要随机的用固定种子），微秒级——它们同时是 doctest 守护的对象
  （示例跑不过测试即红）与单测回收钉的载体（解析恒等式 ≤1e-12）；
- service 层的 critique/fix 也是确定性函数（自治环里 LLM 只编排与
  解释，判读不交给模型）。

## 为什么适配器走"基类 + 注册表"

"可替换组件"（EM 求解器：openems/hfss/palace/comsol/elmer/meep/ngsolve…）
一律用 `EMSolverAdapter` 基类 + `EMSolverRegistry` 注册表模式：新适配器
= 模块级 `register` 调用一次即被发现（entry-points 发现口见
docs/plugins.md），壳层与优化外环完全不感知具体求解器。这就是 fake →
openEMS → HFSS 多保真切换只是换 `--adapter` 参数的原因。

适配器目录里也住着另一类"可选能力配套件"——它们本身不求解，作用是
让真机链路更稳的 helper，一律走 **fail-soft 纪律**（观测面/增强面绝不
阻塞业务主路径，#105）：如 `adapters/pyedb_preload.py`（import pyedb
之前预载 AnsysEM 自带 OpenSSL DLL，规避同名 DLL 对撞硬崩——任何失败
只落 `ok=False + reason` 信封、绝不抛异常，幂等可重入）。判别标准：
失败的最坏后果是"该增强没生效"而非"主流程中断"，才允许进这个位置。

## 为什么判据（verdict）必须预声明

仿真自动化的最大风险不是算得慢，而是**坏数据被采信**（截断当物理、
部分矩阵当满矩阵、常数谷当优化成功）。所以判读逻辑全部内核化为确定性
门（如 G11 健康体检），判据在真跑前声明、跑完不修改；证据不足如实报
UNKNOWN。这个设计取向的历史成本（每条教训一个编号）在
`rfauto runs health` 的"依据"列里可见。

## 给贡献者的推论

- 加功能：先 service 函数 → 壳层薄包装 → 定向单测；别在 CLI/MCP 里写
  逻辑；
- 加可替换组件：基类 + 注册表，不走 if-else 分发；
- 加物理数字：只能进 core（纯函数）或综合引擎，壳层与 agent 永远不写
  公式；
- 分层合法性不用自觉维护——跑测试门，import-linter 会告诉你。
