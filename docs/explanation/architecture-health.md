# 解释：架构健康度一页（架构债地图）

> 这是一篇 explanation：给未来开发者的一页式架构现状/健康指标/改进路线。
> 出处：R1 架构整体健康度深度审计（内部证据目录，
> 2026-10-19，AST 全量 import 图+Tarjan SCC+注册面普查）+ 架构批 战役
> 各重构席的清偿进度（截至 2026-10-19 W14 时点，本文件即 W14-S1 落笔）。
> 数字口径凡未注明"实测"者均为 R1 审计值；live 指标标注了消费门，
> 以门为准。

## 一、一句话现状

**骨架优秀、中段肥胖、语义漂移——方向纪律已经钉死，体量与同层环是
主要存量债。** 分层上下方向由 import-linter 钉牢（实测 2 kept /
0 broken，1055 文件 2582 依赖，契约覆盖 100%）；service 层是体量与
耦合双高发区；AGENTS 分层链条文本 `service → linkage/optimization/
models → adapters` 与代码现实（service 直编 adapters+core，中间层
消费面近乎空转）存在结构性偏差（T4，待用户裁决）。

## 二、六面记分卡（R1 口径 + W14 时点增量）

| 面 | R1 等级 | 一句话依据 | W14 时点增量 |
|---|---|---|---|
| 分层方向纪律 | **A** | 跨层环=0，core 稳定叶子 | T3 收口：13 层契约覆盖 100%（mcp_tools/measurement 入层） |
| 分层语义（链条 vs 现实） | **C** | service→adapters 28 边/~50 文件旁路中间层，service→linkage 仅 6 边 | 未动（T4 待裁决） |
| 模块粒度 | **C-** | src >800 行 104 文件（31%） | T2 首战：api/ui_service/r3_services 三巨石拆包（service 最大文件 2520→1532 行） |
| 依赖卫生（环/lazy） | **C** | 19 模块同层 SCC（15,839 行）、34 环边 28 条 lazy 掩盖 | T1 首战（W6-S1）：叶化 8 面+服务定位器（agent_actions）；lazy 标注约定落地（下节） |
| 测试架构 | **B-** | conftest fixture 9 vs 本地散装 446；`_isolated`×55；parametrize 3.3% | T5 五批收编 50 份（ALLOWLIST 48→38→28；批5=W15-S3）+卫生棘轮；T9 首批参数化（test_calculators 3 组 +8 用例） |
| 注册表面 | **C+** | 35+ 注册面、11 处手写同构 dict、新键 6+ 消费者税 | T6 首战：RegistryKit 落地+3 面迁移（W10-S3） |

## 三、健康指标（live 口径与消费门）

| 指标 | 现值（2026-10-19 W16-S3 复核） | 消费门/复核方式 |
|---|---|---|
| 分层契约 | 13 层，2 kept / 0 broken | `lint-imports --config .importlinter`（merge_preflight 第 3 步） |
| CALC 注册键 | 306（+1 实验键=307） | #231 五钉（test_calculators EXPECTED / test_physics_invariants / test_model_docs / test_experimental_calculators / 模板一致性），新键必同步 |
| conftest 隔离单源 | `tests/conftest.py::isolated` + `isolated_cache_off` 两形态；本地余量 28 份（ALLOWLIST 只可删不可加） | tests/unit/test_conftest_fixture_hygiene.py（AST 棘轮） |
| lazy import 约定 | 白名单三原因（startup-cost=cli/ui 专用 / cycle-break / run-path=service 专用）；示范钉零 6 文件（cli scattered/bands_uq/workflow 66 站 + service api/run_core、calibration_service、rest_api 86 处）；cli 层未标注预算 300（实测 271） | tests/unit/test_lazy_import_convention.py；约定文 docs/explanation/lazy-import-conventions.md |
| 信封契约枢纽 | service.envelope 入度 237（全库 23%）——健康枢纽，#105 红线 | 信封契约测试（merge_preflight 第 5 步） |
| calc_families 聚合面 | 出度 106 但反向消费 0 → 已契约为"仅注册面" | .importlinter forbidden 契约（W11-S3/T7） |
| service 大文件 | >500 行 73 文件（拆包后文件数 270） | 无自动门，T2 台账（下节） |

## 四、改进路线（剩余账，按序）

1. **T1 续：service 同层环清偿**——19 模块 SCC 余量与 6 个直接 2-环
   （fab↔uq、robustness↔uq 等）按"门面/实现分离+叶化"工艺逐对解
   （先例：agent_actions 定位器、*_leaf 叶模块）；解环后可对 service
   开同层 forbidden/independence 子契约防回潮。
2. **T2 续：service 巨石拆分**——现最大 lake_compact_service(1532)、
   rest_api(1416)、remote_service(1322) 等 73 文件 >500 行；工艺复刻
   mcp_server→mcp_tools（dir() 快照钉公开面，门面保名 re-export）；
   迁 lazy import 回模块顶时必须逐站核对 patch 缝（见约定文 run-path 条）。
3. **T4：分层铁律文本对齐（需用户裁决）**——方案 A=承认 service 直编
   adapters/core 的现实并改写 AGENTS 链条与 .importlinter 注释；
   方案 B=逐域下沉（R1 不推荐，成本高且中间层仍空心）。
4. **T5 批 6+：conftest fixture 收编余量 28 份**（批 5=W15-S3 收编 10 份
   48→38→28；余量含 kicad/sim_ci/rest 专用变体，需专用超集适配器形态）；
   R1 估算全库本地 fixture 446 个。
5. **T6 续：RegistryKit 迁移扩面**——存量 11 处手写注册表分批迁
   六件套基类；《新增计算器 checklist》工具化（把 #231 五钉清单
   变成 docs_site 一页）。
6. **T8 续：cli.domains 越级边收口**（23 条：core 9/infra 5/adapters 5/
   optimization 2/pipeline 1/models 1）——纯展示类包 service 函数、
   编排类下沉，收口后由 forbidden 契约钉死。
7. **T9 扩面：注册表驱动测试参数化**——test_physics_invariants(4202 行)
   /per-adapter 冒烟类同构断言逐组合并（先例：test_calculators 三组，
   2026-10-19 W14-S1）。

执行纪律：每步合流前跑 scripts/merge_preflight.py；不触碰 runs/ 证据区
与门双轨制（终门=串行 v2 分段）；子代理并发 ≤3-4。

## 五、新增代码速查（三本书）

- **分层**：新 import 先问方向——只准向下；壳层薄（路由+渲染）、
  数值只在 core（规则 7）、service JSON 进出（规则 4）。
- **lazy import**：函数内 import 必须带白名单标注或迁模块顶——
  判定速查见 docs/explanation/lazy-import-conventions.md。
- **注册面**：新键先查 #231 五钉消费者清单；新注册表用 RegistryKit。
