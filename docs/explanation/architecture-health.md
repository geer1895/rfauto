# 解释：架构健康度一页（架构债地图）

> 这是一篇 explanation：给未来开发者的一页式架构现状/健康指标/改进路线。
> 数字来源：2026-10-19 的一次全仓架构审计（AST 全量 import 图 +
> Tarjan SCC + 注册面普查），以及随后各轮重构的清偿进度。凡未注明
> "实测"的数字均为审计当次值；live 指标以标注的消费门为准。

## 一、一句话现状

**骨架优秀、中段肥胖、语义漂移——方向纪律已经钉死，体量与同层环是
主要存量债。** 分层上下方向由 import-linter 钉牢（2026-10-19 审计
2 kept / 0 broken，1055 文件 2582 依赖；**2026-11-07 aurora_q Q-X24
复核 3 kept / 0 broken，1260 文件 3293 依赖**——第三契约=aurora_h
W2-S1 增设的 cli/mcp_tools 白名单棘轮，契约覆盖仍 100%）；service
层是体量与耦合双高发区；AGENTS 分层链条文本 `service → linkage/
optimization/models → adapters` 与代码现实（service 直编
adapters+core，中间层消费面近乎空转）存在结构性偏差（T4，尚未定）。

## 二、六面记分卡（审计口径 + 清偿进度）

| 面 | 审计等级 | 一句话依据 | 清偿进度 |
|---|---|---|---|
| 分层方向纪律 | **A** | 跨层环=0，core 稳定叶子 | T3 收口：13 层契约覆盖 100%（mcp_tools/measurement 入层） |
| 分层语义（链条 vs 现实） | **C** | service→adapters 28 边/~50 文件旁路中间层，service→linkage 仅 6 边 | 未动（T4 尚未定） |
| 模块粒度 | **C-** | src >800 行 104 文件（31%） | T2 首战：api/ui_service/r3_services 三巨石拆包（service 最大文件 2520→1532 行） |
| 依赖卫生（环/lazy） | **C** | 19 模块同层 SCC（15,839 行）、34 环边 28 条 lazy 掩盖 | T1 首战：叶化 8 面+服务定位器（agent_actions）；lazy 标注约定落地（下节） |
| 测试架构 | **B-** | conftest fixture 9 vs 本地散装 446；`_isolated`×55；parametrize 3.3% | T5 五批收编 50 份（ALLOWLIST 48→38→28）+卫生棘轮；T9 首批参数化（test_calculators 3 组 +8 用例） |
| 注册表面 | **C+** | 35+ 注册面、11 处手写同构 dict、新键 6+ 消费者税 | T6 首战：RegistryKit 落地+3 面迁移 |

## 三、健康指标（live 口径与消费门）

| 指标 | 现值（2026-10-19 复核） | 消费门/复核方式 |
|---|---|---|
| 分层契约 | 13 层，**3 kept / 0 broken**（2026-11-07 aurora_q Q-X24 复核：1260 文件 3293 依赖；第三契约=aurora_h W2-S1 T8 cli/mcp_tools 白名单棘轮，25 ignored 只收不放） | `lint-imports --config .importlinter`（merge_preflight 第 3 步） |
| CALC 注册键 | 306（+1 实验键=307） | #231 五钉（test_calculators EXPECTED / test_physics_invariants / test_model_docs / test_experimental_calculators / 模板一致性），新键必同步 |
| conftest 隔离单源 | `tests/conftest.py::isolated` + `isolated_cache_off` 两形态；本地余量 28 份（ALLOWLIST 只可删不可加） | tests/unit/test_conftest_fixture_hygiene.py（AST 棘轮） |
| lazy import 约定 | 白名单三原因（startup-cost=cli/ui 专用 / cycle-break / run-path=service 专用）；示范钉零 6 文件（cli scattered/bands_uq/workflow 66 站 + service api/run_core、calibration_service、rest_api 86 处）；cli 层未标注预算 300（实测 271） | tests/unit/test_lazy_import_convention.py；约定文 docs/explanation/lazy-import-conventions.md |
| 信封契约枢纽 | service.envelope 入度 237（全库 23%）——健康枢纽，#105 红线 | 信封契约测试（merge_preflight 第 5 步） |
| calc_families 聚合面 | 出度 106 但反向消费 0 → 已契约为"仅注册面" | .importlinter forbidden 契约（T7） |
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
3. **T4：分层铁律文本对齐（待定）**——方案 A=承认 service 直编
   adapters/core 的现实并改写 AGENTS 链条与 .importlinter 注释；
   方案 B=逐域下沉（审计不推荐，成本高且中间层仍空心）。
4. **T5 批 6+：conftest fixture 收编余量 28 份**（批 5 收编 10 份
   48→38→28；余量含 kicad/sim_ci/rest 专用变体，需专用超集适配器形态）；
   审计估算全库本地 fixture 446 个。
5. **T6 续：RegistryKit 迁移扩面**——存量 11 处手写注册表分批迁
   六件套基类；《新增计算器 checklist》工具化（把 #231 五钉清单
   变成 docs_site 一页）。
6. **T8 续：cli.domains 越级边收口**（23 条：core 9/infra 5/adapters 5/
   optimization 2/pipeline 1/models 1）——纯展示类包 service 函数、
   编排类下沉，收口后由 forbidden 契约钉死。
7. **T9 扩面：注册表驱动测试参数化**——test_physics_invariants(4202 行)
   /per-adapter 冒烟类同构断言逐组合并（先例：test_calculators 三组，
   2026-10-19）。

执行纪律：每步合流前跑 scripts/merge_preflight.py；不触碰 runs/ 证据区。

## 五、新增代码速查（三本书）

- **分层**：新 import 先问方向——只准向下；壳层薄（路由+渲染）、
  数值只在 core（规则 7）、service JSON 进出（规则 4）。
- **lazy import**：函数内 import 必须带白名单标注或迁模块顶——
  判定速查见 docs/explanation/lazy-import-conventions.md。
- **注册面**：新键先查 #231 五钉消费者清单；新注册表用 RegistryKit。

## 六、aurora_q 战役新增面（2026-11-07 Q-X24 实测追加）

> aurora_q（2026-11-04 开工，收官终门 wf_gate_full_aurora_q_final2 =
> 32195 passed / 0 failed / 23 skipped，GATE_RC=0）新增十二面逐项分层
> 合规记录。测试覆盖两口径并列：**台账**=各席交付时主代理独立验收数
> （runs/aurora_q/SEATS.md 交付摘要，pytest 展开口径）；**静态**=本次
> `grep "def test_"` 计数（不含参数化展开，两差=参数化倍数非矛盾）。

### 6.1 逐面台账（层位全部合规，零越级新边）

| 新增面 | 层位（分层合规形态） | 测试覆盖（台账/静态） | 备注 |
|---|---|---|---|
| em_bench 扩容（T-Q24+Q-X15） | service/em_bench_service.py | 37+15 / 71 | 判据闭集实测 **8**（原 7+fsv_grade）；default 任务运行时实测 **9**（Q-X15 扩 6→8 后，Q-X22 在飞席增补 ssl_anchor 族——函数 docstring "8" 为其时点口径）；阈值预声明 fail-closed（#122） |
| animation 动图管线（T-Q3） | service/animation/（spec/loaders/renderers） | ~214 / 220 | 渲染器实测 **17** 图型（第 17=cfc_state，Q-R3R 遗留清偿席补齐）；确定性显示变换零语义改写 |
| format_overview（T-Q5） | service/format_overview_service.py | 75→115 / 80 | kind 实测 **8**（touchstone/kicad_pcb/drawio/gdsii/dxf/ipc2581/odbpp/ads_ds）；每 kind 独立 schema_version 常量 |
| vendor_doc FTS5（T-Q19） | service/vendor_doc_service.py | 35 / 58 | SQLite FTS5 external-content 虚表（实测 L83）；PDF/CHM/HTML 三通道+LIKE 回退+zero_ingest_audit；真机冒烟召回 9/10 |
| geometry_lint（T-Q26b） | service/geometry_lint_service.py | 32 / 32 | 六检查实测（端口三态/部分相交/长宽比/变量单位）；零 pyaedt 依赖 |
| layered_stack 模板族（T-Q26d） | adapters/layered_stack_spec.py+hfss_builder_layered.py+openems 渲染+TEMPLATE_META 注册 | 57+20 / 84 | TEMPLATE_META 实测 **76**（八面同数）；双引擎渲染+反解 7.1e-15Ω（#118 家法） |
| KiCad sch_gen（T-Q22） | adapters/kicad_sch_gen.py（纯 stdlib s-expr 生成器）+service/kicad_sch_service.py | 53 / 51 | adapters 面零第三方依赖（子进程封装在 service）；真机三方一致冒烟 |
| roundtrip_certificate（T-Q23） | service/roundtrip_certificate.py | 21 / 21 | 通用"生成→回读→比对"二值证书件（fold_diff 确定性排序；pass 判定权与 diff 结构强一致） |
| gradient_consistency（T-Q21 通道 1） | service/gradient_consistency_service.py | 49（三通道合计） / 21 | 零物理零引擎依赖，provider 注入缝（cosine≥0.999+rel-err≤5% 预声明） |
| adjoint 双桥（T-Q21 通道 2/3） | service/adjoint_surrogate_bridge.py+adjoint_optimizer_link.py，内核 core/inverse_adjoint.py | （含上栏 49） / 53 | 梯度数值只出确定性内核（规则 7）；桥只做编排不产数 |
| fd_judge（Q-X20） | 内核 core/suspended_stripline_fd_judge.py+服务壳 service/suspended_stripline_judge_service.py | 23 / 42（fd_judge 23+template 19） | 规则 4/7 标准形态：静流裁判内核在 core，服务壳只组装 JSON；外部观测锚冻结常量随行登记出处 |

### 6.2 本役印证的分层约束（新增代码遵守既有约束的活例）

- **adapters→service 禁直插**：geometry_lint 接线即范本——适配器层禁
  import service（layers 契约），`hfss_adapter.build_and_setup` 的钩子
  只消费调用方经 `lint_geometry` 预算好的报告信封（键 ok/lint_pass/
  issues），ERROR 级在 build 出口抛 ModelBuildError 拦截；缺省关零行为
  变化。凡"适配器要吃 service 判读"一律走此消费形态，不开新越级边。
- **内核在 core、服务壳在 service**（规则 4+7 标准形态）：fd_judge——
  静流收敛/裁判数学在 core（零仿真、铁律 7），service 壳只组装 JSON
  信封；同族 adjoint（inverse_adjoint 内核+双桥编排）。
- **信封契约全走构造器**：em_bench/geometry_lint/format_overview/
  vendor_doc 等新面出口一律 ok_envelope/error_envelope（Q-R4 审查曾拦
  em_bench 信封契约 P1 一处即此门的效力实证）。
- **声明式输入+确定性显示变换**：animation 17 渲染器与 KiCad sch_gen
  （按引脚名连通的 label 制表示法）均把坐标/布局参数钉为声明式 spec，
  渲染层零语义改写——铁律 7 在展示面的推广。
- **import-linter 三契约全 kept**（2026-11-07 实测）：layers 13 层
  （10 ignored 白名单）+calc_families forbidden（12 ignored）+
  cli/mcp_tools 白名单棘轮（25 ignored，aurora_h 起只收不放）；本役
  新增面未新增任何 ignored import（棘轮零放行）。

### 6.3 与存量账的关系

- 本役新增面全部落在 service/adapters/core 既有层位，未改变 §二记分卡
  各面等级；service 大文件面（T2 台账）2026-11-07 实测更新：>500 行
  100 文件（service 总 368 文件；审计时 73/270）——增量主要来自本役
  em_bench_service（1918 行，service 第二大，仅次于
  design_replay_report 2686，后续拆分候选）与 format_overview/
  vendor_doc 等单文件面。登记不展开。
- §四改进路线各项（T1 同层环/T4 链条文本/T5 fixture 余量/T6 RegistryKit
  扩面等）在本役期间未推进也未回潮，账面不变。
