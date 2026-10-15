# Reference：权威出处指针

> 本页**只给指针，不复制内容**——单一事实源原则（SNRO）：任何接口的
> 权威描述在它自己的 docstring / `--help` / 清单产物里，本文档只负责
> 告诉你去哪找。复制出来的表格会烂，指针不会。

## CLI

| 要找什么 | 去哪 |
|---|---|
| 全部命令与参数 | `rfauto --help`，逐子命令 `rfauto <cmd> --help`（权威出口，永远与代码同步） |
| 快速上手样例 | README「快速开始」「CLI 命令一览」节 |
| 逐命令教程 | docs/tutorials/getting-started.md；docs/how-to/ 各篇 |

当前规模（2026-10-14 实测，与 `scripts/check_numbers.py` 同源）：CLI 269 个
叶子命令（main 263 + bench 6）；单元测试 25433（全量门口径）。规模数字以
该脚本实跑为准，此处快照仅作量级参考。

机读出口（架构面，防手抄漂移）：`rfauto rest schema --json`（REST
`/api/v1` 全端点清单，25 端点实测）；`rfauto pitfalls search <关键词>`
（坑账确定性词面检索，只读）。

## 计算器（`rfauto calc`）

| 要找什么 | 去哪 |
|---|---|
| 全部计算器键/参数表/公式出处（权威出口，**实时**） | `rfauto calc list`（`--json` 机读；实验键带【实验】标签，运行需 `--allow-experimental`） |
| 执行单键 | `rfauto calc run <键> -p 参数=值 …`（`-p` 可重复；示例见 `rfauto calc run --help`） |
| UI 交互面 | 看板「微波工具箱」页（`#/tools`）：按组下拉+搜索、结果自动画图/热图、扫参模式（2–101 点）、`#/tools/<键名>` 深链直达——与 CLI/MCP 同一内核 |

规模快照（2026-10-11 实测）：`CALCULATOR_REGISTRY` 164（含实验键 165，
16 业务组+实验组）。键数与分组**以 `rfauto calc list` 实时输出为准**——
本页不钉死数字，注册表扩键后此处无需跟改。

## Python API（模块 docstring = 单一事实源）

入口模块速查（完整 API 看 `help(<module>)` 或源码 docstring）：

| 模块 | 职责 |
|---|---|
| `rfauto.core.synthesis` | 微带综合（HJ 闭式 + brentq 反解）、Wilkinson/branchline/patch/BPF |
| `rfauto.core.cascade` | 级联预算 + 混频杂散搜索（纯函数；docstring 带可运行示例） |
| `rfauto.core.wcd` | WCD 设计中心化 + Cpk（纯函数；docstring 带可运行示例） |
| `rfauto.core.calculators` | 微波闭式计算器注册表（`rfauto calc` 的内核） |
| `rfauto.service.api` | 服务层门面（run_once/sweep/tune，JSON 进出） |
| `rfauto.service.calculator_service` | 计算器清单/执行（UI/CLI/MCP 三壳共享） |
| `rfauto.service.health_service` | run 健康度体检（G11 门权威实现） |
| `rfauto.adapters.em_solver_base` | EMSolverAdapter/EMSolverRegistry（适配器契约与发现口） |
| `rfauto.adapters.openems_templates` | 72 个模板的 CSXCAD 渲染（TEMPLATE_META/TEMPLATE_NOMINAL/render_script） |

**doctest 制度**：上表标注"带可运行示例"的模块，其 docstring 示例由
测试守护——示例跑不过测试即红，文档与代码不会脱钩：

```bash
# 缺省套件内（毫秒级）
pytest tests/unit/test_docs_doctest.py -q
# opt-in 原生收集（仓库根 conftest.py 白名单）
pytest src/rfauto/core --doctest-rfauto -q
# 零配置等价：pytest 原生 flag 只点名白名单文件
pytest --doctest-modules src/rfauto/core/cascade.py src/rfauto/core/wcd.py
```

## MCP

- 工具清单权威出口：MCP 服务器自注册表导出的 `mcp/manifest.json`
  （发布产物布局见 README「发布」节）；
- 客户端接入（Claude Desktop/Cursor 配置示例、stdio 传输、与 CLI 共享
  状态）：README「MCP Agent 接口」节；当前 **152 个工具 + 9 个
  resources**（`@mcp.tool`/`@mcp.resource` 实测计数，2026-10-14）；
  发布产物布局见 README「发布就绪与手动发布步骤」节。

## 模板与 RF 口径

| 要找什么 | 去哪 |
|---|---|
| 每个模板的名义参数/冒烟口径/参数语义 | `docs/templates/<模板名>/meta.yaml` |
| 模板清单（72 个） | `rfauto.adapters.openems_templates.TEMPLATE_META` |
| 端口/网格铁律、验收基准 dB 值、官方例出处 | docs/rf_template_references.md |
| COMSOL API 口径与本地 PDF 索引 | docs/comsol_references.md |
| openEMS 源码构建 | docs/openems_build_guide.md |

## 配置与稳定性

| 要找什么 | 去哪 |
|---|---|
| 层叠库（εr/厚度，带 source/verified_by） | `configs/materials.yaml` |
| 求解器注册（openems/hfss/palace… exe 路径） | `configs/solvers.yaml` |
| 本机覆盖（不入 git） | `configs/settings.local.yaml` |
| 公开 API 面/弃用窗口/快照门 | docs/stability_policy.md |
| 插件开发（适配器/模板接入） | docs/plugins.md |
| 架构分层为什么这样设计 | docs/explanation/layered-architecture.md |
| UI 架构（routes 分域/统一事件流/前端模块） | docs/explanation/layered-architecture.md「UI 架构」节；REST 端点机读清单 `rfauto rest schema` |
