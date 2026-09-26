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

## 为什么 service 层是"JSON 进出"

CLI、MCP server、UI 三种壳共享同一业务，唯一可行的共享点是"参数进、
JSON 出"的门面函数。规则：

- **新功能先写 service 函数**，壳层只做参数解析、调用、渲染（薄壳零
  逻辑）。你在 `rfauto calc run` 里看不到一行公式，它只是
  `service.calculator_service.run_calculator` 的渲染器；
- 错误语义统一：`ok=False + error` 而非异常穿透到壳——脚本消费者靠
  退出码判成败，不必解析异构输出。

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
