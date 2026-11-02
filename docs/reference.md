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

当前规模（2026-11-02 实测，与 `scripts/check_numbers.py` 同源）：CLI 297 个
叶子命令（non-bench 291 + bench 6）；单元测试 30738（check_numbers 口径
=全量门日志 passed+failed）。规模数字以该脚本实跑为准，此处快照仅作
量级参考（本页三数字已入该脚本 DOC_PATTERNS 门控，漂移即门红）。

机读出口（架构面，防手抄漂移）：`rfauto rest schema --json`（REST
`/api/v1` 全端点清单，25 端点实测）；`rfauto pitfalls search <关键词>`
（坑账确定性词面检索，只读）。

## 计算器（`rfauto calc`）

| 要找什么 | 去哪 |
|---|---|
| 全部计算器键/参数表/公式出处（权威出口，**实时**） | `rfauto calc list`（`--json` 机读；实验键带【实验】标签，运行需 `--allow-experimental`） |
| 执行单键 | `rfauto calc run <键> -p 参数=值 …`（`-p` 可重复；示例见 `rfauto calc run --help`） |
| UI 交互面 | 看板「微波工具箱」页（`#/tools`）：按组下拉+搜索、结果自动画图/热图、扫参模式（2–101 点）、`#/tools/<键名>` 深链直达——与 CLI/MCP 同一内核 |

规模快照（2026-10-19 实测复核，与 `scripts/check_numbers.py` 同源）：
`CALCULATOR_REGISTRY` 340（含实验键 341，16 业务组+实验组；aurora_g
战役期间自 248 净增 49 键，`git diff cdad7549..HEAD --stat` 口径）。
键数与分组**以 `rfauto calc list` 实时输出为准**——本页不钉死数字，
注册表扩键后此处无需跟改。

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
| `rfauto.adapters.openems_templates` | 75 个模板的 CSXCAD 渲染（TEMPLATE_META/TEMPLATE_NOMINAL/render_script） |

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
  状态）：README「MCP Agent 接口」节；当前 **166 个工具 + 10 个
  resources**（`@mcp.tool`/`@mcp.resource` 实测计数，2026-11-01，
  与 `scripts/check_numbers.py` 同源）；
  发布产物布局见 README「发布就绪与手动发布步骤」节。

## 模板与 RF 口径

| 要找什么 | 去哪 |
|---|---|
| 每个模板的名义参数/冒烟口径/参数语义 | `docs/templates/<模板名>/meta.yaml` |
| 模板清单（75 个） | `rfauto.adapters.openems_templates.TEMPLATE_META` |
| 端口/网格铁律、验收基准 dB 值、官方例出处 | docs/rf_template_references.md |
| COMSOL API 口径与本地 PDF 索引 | docs/comsol_references.md |
| openEMS 源码构建 | docs/openems_build_guide.md |

## 配方 schema（`validate` / `run` / `tune` / `sweep` 的 YAML 配方）

单一事实源（本节各表与之逐项钉住，漂移即门红，钉在
`tests/unit/test_recipe_schema_doc.py`）：顶层键白名单
`src/rfauto/service/recipe_validation.py::RECIPE_TOP_LEVEL_KEYS`；ops 枚举
与指标名清单 `src/rfauto/core/objectives.py`（`MetricOp` /
`OBJECTIVE_METRIC_NAMES`）。键级错误（顶层键/参数名/指标名拼写、空
objectives）在 `rfauto validate` 即报错并附「你是不是想写」提示
（CLI 与 UI 表单保存同严；示例实例库 `recipes/*.yaml`）。

### 顶层键

| 键 | 必需 | 语义 |
|---|---|---|
| `model` | 必需 | 目标模型（models 注册表键；`rfauto models list`） |
| `params` | 必需 | 设计参数（键=该模型 params_model 字段名，见「参数名」小节） |
| `setup` | 可选 | 仿真设置（缺席用默认值；键面见「setup / export 键」小节） |
| `objectives` | 可选 | 优化目标列表（缺席合法=plain run；在场不可为空） |
| `optimization` | 可选 | 调参段：`params`（搜索空间 low/high）、`constraints`（约束，元素结构同 objectives） |
| `limits` | 可选 | 配额：`max_trials` / `max_wall_hours` |
| `export` | 可选 | 导出选项（见「setup / export 键」小节） |
| `ops` | 可选 | 变异算子（optimization/mutation 消费） |
| `tolerance` | 可选 | 公差分析：`tolerances` / `n_samples`（`rfauto tolerance` 消费） |
| `units` | 可选 | 单位制 `mm`（缺省）/ `um`（IPD 工艺） |
| `design_name` | 可选 | HFSS 设计名（缺省 RFADesign） |
| `recipe_version` | 可选 | 配方 schema 版本（与插件 `schema_version` 语义区分，勿混） |
| `schema_version` | 可选 | 插件参数 schema 版本 |
| `notes` | 可选 | 人类备注 |

### 参数名（动态面，随模型走）

| 要找什么 | 去哪 |
|---|---|
| 某模型合法参数名/缺省值/取值域 | `rfauto models list --schema <model>`（单源=模型插件 `params_model`） |
| 模型清单 | `rfauto models list` |
| 75 个 openEMS 模板的参数面 | `rfauto template-spec list` / `rfauto template-spec draft`（单源=`adapters/openems_templates.TEMPLATE_META`） |

### objectives 的 ops（`MetricOp` 枚举）

| op | 语义 |
|---|---|
| `max_below` | 区间最大值 ≤ value |
| `min_above` | 区间最小值 ≥ value |
| `mean_within` | 区间均值在 value=[low, high] 内 |
| `bandwidth` | 满足条件的带宽 ≥ value |

### 指标名（objectives/constraints 的 `metric` 合法值）

| 指标名 | 语义 |
|---|---|
| `s11_db` | 带内 \|S11\| 最大值 dB（worst-case 包络；#195 常数陷阱口径） |
| `s11_db_min` | 带内 \|S11\| 最小值（谷深语义，#195） |
| `s11_db_max` | 带内 \|S11\| 最大值（显式统计量变体） |
| `s21_db` | 带内 \|S21\| 均值（插损） |
| `iso_s23_db` | 端口 2→3 隔离度（需 ≥3 端口网络） |
| `bw_ghz_s11_lt_-10` | S11<-10dB 的带宽（GHz） |
| `eps_eff` | 均匀线有效介电常数（S21 相位斜率口径，需 `length_mm`） |
| `gain_db` | 远场增益（需 far_field 数据） |

### setup / export 键

| 段 | 键 | 消费处 |
|---|---|---|
| `setup` | `name` `sweep_name` `freq_range_ghz` `points` `convergence_delta` `max_passes` `minimum_passes`（AEDT 原生大小写作别名同收）`solver` `radiation_box` | HFSS 链：`adapters/hfss_session.py::HFSS_SETUP_KNOWN_KEYS`（P2 白名单，白名单外键显式报错）；fake 链用内置 main_setup |
| `export` | `touchstone.renorm_ohm` / `touchstone.deembed` | 声明性段：随配方快照留档；run 链 Touchstone 导出契约由 `AdsExchangeContract` 按插件端口数派生 |

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
