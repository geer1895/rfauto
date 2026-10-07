# 架构与方法论：分层、锚体系与判据先行

> 本页回答"为什么这样设计"。分层图与逐层职责的完整版见
> [分层架构（explanation）](../explanation/layered-architecture.md)；
> 本页补三件护栏：分层纪律、锚体系、判据先行。

## 分层纪律（可机检）

```
cli / mcp_server / ui   →  service  →  linkage / optimization / models
                                       →  adapters  →  pipeline  →  infra  →  core
```

- 依赖只准自上而下，由 import-linter 在门上强制（"分层架构不可破"）。
- 服务层 JSON 进出：新功能先写 service 函数，CLI/MCP 是薄壳——
  同一能力天然同时面向人（CLI/UI）与代理（MCP）。
- 可替换组件用"基类 + 注册表"模式（`EMSolverAdapter`/`EMSolverRegistry`、
  `CALCULATOR_REGISTRY`、模板注册表、agent runtime 注册表）。

## 锚体系：让"信谁"有账本

仿真链路上的每个关键标量（谐振频率、Q、耦合度、损耗）都可能出错——
建模错、网格错、判读错。rfauto 用**锚（anchor）**把"信谁"显式化：

- **标定锚**：闭式综合 / 参考实现 / 真机标定产物之间的对拍基准，
  逐条记录出处与适用域；
- **仲裁锚**：HFSS 作为对齐基准，其他引擎/设计值向它对齐；
  经仲裁背书的经验常数才能进配方的 band×bounds 设计依据；
- 锚注册表落在 `knowledge/anchors.yaml`，与 core 单源双向核对
  （条数不一致即判红），由 `rfauto anchors` 系列命令消费。

锚的纪律：**同源数字互证是同义反复**——两个口径互证时必须有第三方门
（解析解/闭式/独立实现）裁定；修正之前先验证模型本身是否正确。

## 判据先行：先定门，再跑数

每个战役/校准/优化在开跑前预声明判读判据（门）：

- 指标名、阈值、数据形态三者必须匹配（窄带谐振器件带内 max 是常数
  陷阱——谷深语义走显式指标名）；
- 预声明门错了也**如实记 FAIL/PARTIAL，不事后改门**；学术诚信优先于
  验收表全勾；
- 判读逻辑是 service 层确定性函数，LLM 只编排与解释——保证 critique/fix
  可复现、模型无关。

## 数值与文档的同一纪律

- 数值只在确定性内核；agent 永不产生物理数字，只产出 typed tool call。
- 文档统计数字（测试数/CLI 数/MCP 工具数/计算器键数/模板数）一律
  构建时从代码面实测回填（`scripts/check_numbers.py` 单源，本站参考页
  即此产物），不沿用上一份文档。

## 延伸阅读

- 分层图与逐层职责：[分层架构](../explanation/layered-architecture.md)
- 30 分钟上手：[getting-started](../tutorials/getting-started.md)
- 机读参考面：[CLI](../reference/cli.md) ·
  [MCP](../reference/mcp.md) ·
  [计算器](../reference/calculators.md) ·
  [模板库](../catalog/index.md)
