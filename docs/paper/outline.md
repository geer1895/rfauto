# 方法学论文骨架（H3，占位——不写正文、不投稿）

> 状态：**骨架/占位**。本文件只固定章节结构、每段要回答的问题与可引用的
> 既有证据（DEVLOG 教训编号、runs/ 既有 JSON）。正文、投稿目标、作者署名
> 均为用户决策；本仓库任何 agent 不得替用户撰写正文或执行投稿。
>
> 数字纪律：正文一切数字只能来自确定性内核产出并可溯到 runs/ 文件
> （AGENTS 规则 7 / 铁律 7）。图表由 `scripts/paper_figures.py` 从既有 JSON
> 离线生成到 `runs/release_staging/paper/figs/`（附 manifest.json 源文件 SHA256），
> 脚本零算术改写、零新数字。

## 0. 题目（占位）

- 候选方向：面向多保真射频 EDA 的锚模板工厂、判据语义与失败模式目录
- 关键词：multi-fidelity calibration, template factory, anchor benchmark,
  failure-mode catalogue, agentic EDA with deterministic kernels

## 1. 摘要（占位，≤200 词）

- 问题：商业/开源求解器（HFSS/openEMS/COMSOL/Elmer）跨保真结果不可直接互换；
  LLM 参与设计流程时数字可信度无保证。
- 方法：锚模板工厂（每模板附闭式/官方例锚与健康判据）+ 确定性内核产数字、
  LLM 只编排 + 公开失败模式目录（结构化教训条目）。
- 证据：引擎基准锚 verdict（`runs/benchmark/*_engine_benchmark.json`）、
  mline 网格收敛（`runs/benchmark/mline_mesh_convergence.json`）、
  WP3.9 工厂基准（`runs/wp39_mvp/summary.json`，三问题如实 FAIL——wall-clock 超门）。
- 结论：占位。

## 2. 引言（占位）

- 2.1 背景：Agentic EDA 综述定位（方案 §10.6 F1 引用 arXiv 2606.19795 handoff perspective）
- 2.2 缺口：EM/RF 域公开基准空白（方案 §10.6 F6 差异化）；"LLM 产物理数字"不可信
- 2.3 贡献列表（占位 3-4 条）

## 3. 方法（占位）

- 3.1 分层架构与确定性边界：cli/mcp → service → … → core（import-linter 契约，
  `.importlinter`）；数字只在 core/service 确定性函数（AGENTS 规则 7）
- 3.2 锚模板工厂：`docs/templates/*/meta.yaml`（38 模板）+ `docs/rf_template_references.md`
  官方例口径；线宽一律 skrf HJ 综合精算（AGENTS 规则 1c）
- 3.3 健康判据与指标语义：谷深走显式 `s11_db_min`（教训 #195/#197）；
  求解健康度九因子（`core/solve_health.py`，方案 §10.7 G11）
- 3.4 跨保真校准：HFSS 为对齐基准（AGENTS 规则"HFSS 结果为对齐基准"，#190）；
  openEMS 柱坐标 k=1 回 HFSS 仲裁中心（#232/#219）
- 3.5 公开/私有双集防污染：`service/dataset_insights.py`（DEVLOG（一百四十八））
- 3.6 失败模式目录（H3 核心贡献，条目=DEVLOG 教训编号，结构化为"症状/根因/
  对策/复现"四元组）：
  - #152 网格近重合线 → CFL 时间步塌缩（症状 CalcPort IndexError）
  - #154 同名参数跨适配器语义相反（wilkinson series/shunt）
  - #174 辐射器件端口面随域走；激励体积为零则"不耦合"
  - #191 HFSS 波端口尺寸实证——模型错优先于引擎错
  - #195 窄带器件带内 max 常数陷阱（47 样本代价）
  - #208 openEMS 跨 Run 绑定对象销毁 → 进程隔离单激励
  - #232 openEMS 柱坐标 MUR 静默退化 PEC
  - #233 Elmer HeatSolver 不消费 `Heat Source`（恒温陷阱）
  - #234 Saltelli 一阶估计量大数相减失效（先居中）

## 4. 实验（占位）

- 4.1 引擎基准锚（图 `fig_anchor_delta_eps.png`）：五锚 delta_eps*_pct 与各自门限
  （via 的 eps2 无门——图上如实标 no gate，不得补门）
- 4.2 网格收敛（图 `fig_mline_mesh_convergence.png`）：mesh_mm 档 vs HJ/gold 偏差
- 4.3 工厂基准 vs 基线（图 `fig_wp39_candidate_vs_baseline.png`）：三问题 candidate/baseline
  原值与 verdict（当前全部 FAIL：wall-clock ratio > 0.5 门——**如实报告，不得修饰**）
- 4.4 消融/敏感性（占位）：Sobol 居中前后对比（#234）；HFSS 仲裁前后模板中心偏移（#219）
- 4.5 复现性：公开数据集导出包（`runs/release_staging/dataset/`，仅 public 集）+
  榜单（`runs/release_staging/leaderboard/`）+ 图 manifest SHA256

## 5. 讨论与局限（占位）

- 商业求解器 license 依赖；单机 Windows 环境（CI 仅 Linux 单元层）
- 工厂基准当前 wall-clock 未达门（如实）；代理环算法红利待 §10.9 薄弱项 1 补全
- 数据集公开集当前为空（用户内容决策未做），复现包机制就绪但内容待放行

## 6. 结论（占位）

## 7. 可复现材料清单

- 代码：本仓库（MIT，`LICENSE`；引用 `CITATION.cff`）
- 图：`scripts/paper_figures.py` → `runs/release_staging/paper/figs/*.png` + `manifest.json`
- 数据：`runs/benchmark/*.json`、`runs/wp39_mvp/summary.json`（只读来源）
- 就绪校验：`python scripts/release_readiness.py --check`（六节；绝不发布）

## 附：写作纪律

- 每个数字旁标源文件相对路径；图题写 "values as recorded"
- FAIL/PARTIAL 结果如实进正文（#122 学术诚信优先于验收表全勾）
- 归因一律标"假设/待证"直至有离线审计或真机复现（#221⑥）
