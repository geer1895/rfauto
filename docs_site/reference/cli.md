# CLI 命令参考

> 实注册叶子命令共 **357** 条（`typer.main.get_command` 后按 click 树 walk 展开，含各 `add_typer` 子应用；与 `scripts/check_numbers.py` 的 `count_cli()` 构建时逐位互证）。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改。

用法速查见[用户指南](../guide/cli-quickstart.md)；单命令细节以 `rfauto <命令> --help` 为准（本页摘 help 首行）。

## rfauto doctor

环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。


## rfauto run

单次仿真（build → solve → post → 导出）。


## rfauto tune

启动优化外环（TPE / NSGA-II / --fidelity auto 多保真）。


## rfauto sweep

参数扫描（先粗扫缩小范围再交给精调）。


## rfauto autotune

确定性 critique 自治调优环（无人在环；数值只在确定性内核）。


## rfauto tolerance

公差/良率分析（Monte Carlo，规格取自 objectives）。


## rfauto refine

热启动续调：以上轮 best 为起点，继续优化。


## rfauto link

把某次 HFSS 结果送进 ADS 联动链路（P3, N=2 往返；--to-ads 才执行）。


## rfauto report

按已完成的 run 重建报告（markdown / html）。


## rfauto export-report-pdf

把已完成 run 的指标导出为多页 PDF 报告（WP4.7）。


## rfauto replay

复现：用该 run 的 recipe 快照重跑，并核对 plugin/schema 版本。


## rfauto validate

校验配方文件（不执行仿真）。


## rfauto correlate

仿真 vs 测量相关性分析。


## rfauto hfss-import

HFSS 工程导入器：读变量/扫参范围/Setup-Sweep/端口 → 设计规格 + 配方草稿。


## rfauto repro

导出可复现包（配方快照 + 求解器输入 + S 参数 + reproduce.py）。


## rfauto repro-manifest

组装复现清单（环境段+可选产物段）并落盘（reproducibility_service）。


## rfauto repro-verify

校验复现清单（产物三态差异+环境 packages/lock 差异，如实报告）。


## rfauto even-odd

奇偶模分解报告（对称性检查+半模型切割+端口改写表+守卫，只读）。


## rfauto p0

方向 1 P0 实验：多保真验证（fake 先行）。


## rfauto sensitivity

灵敏度分析：Sobol/Morris 参数重要度排序（方向 8b）。


## rfauto tuning-report

生成增强调优报告（方向 8c）：指标摘要 + 诊断 + 可复现信息。


## rfauto audit

查看 Agent 审计日志（audit.jsonl）。


## rfauto simci

全配方夜间回归：validate+run → 对照 runs 索引历史基线 → diff 报告。


## rfauto simci-pin-baseline

sim_ci golden 基线三动作：pin 钉定 / compare 对照 / drift 漂移量化。


## rfauto inbox

审批收件箱：查看/批准待确认的 Agent 提案（方向 6i）。


## rfauto chat

LLM 对话窗（方向 6j 双通道可选）：内嵌 service 直调 或 MCP 客户端。


## rfauto chat-test-connection

LLM 通道接通性检测（最小探针 + 分诊结论：额度/限速/认证/网关）。


## rfauto sparams-compare

run 与外部 .sNp 的 S 参数叠画对比（dB，WP0.3/E8）。


## rfauto ui

启动人工核验 UI（浏览器查看/修改配方、3D 模型、S 参数与中间产物）。


## rfauto warm-start

数据集历史样本 → warm-start 先验注入优化（相似度门在 warm_start 内）。


## rfauto electrothermal

Wilkinson 隔离电阻损耗 → 温升 → 材料温漂 → S 参数失谐（+带内判据），纯闭式。


## rfauto parasitic

PCB 互连 RLC 提取链：pcell 几何 → RF-DRC 门 → 闭式锚 →（Q3D 注入对比 ≤5％ 门）。


## rfauto tolerance-allocate

cost-aware 公差分配（敏感度×成本系数 → 逐参数公差建议 + 对照法 + Cpk）。


## rfauto topology

滤波器拓扑提议（typed，禁数值字段）→ 综合初值 →（--campaign）小战役精算。


## rfauto vna-replay

mock 仪表采集→校准→相关全链回放（零硬件；硬件阻塞下的回归入口）。


## rfauto report-narrative

F9 叙述位：run 白名单 → 确定性模板叙述，或审计外来叙述（未授权数字定位；不调 LLM）。


## rfauto verdict-summary

verdict.json → 人读摘要（总判定+门清单+关键指标，确定性零 LLM）。


## rfauto explain-run

失败指纹解释（DP-17 W2：确定性指纹匹配→候选根因族+取证命令+坑号链，无 LLM）。


## rfauto compose

模板几何组合（DP-8）：netlist YAML → 单一 simulation.py（布局合并路线）。


## rfauto compose-templates

列出已注册组合契约模板与 pin schema（DP-8 opt-in 台账）。


## rfauto certify

公差盒 → 指标区间证书（三值门面：逐目标 PASS/FAIL/UNKNOWN + 总 verdict）。


## rfauto solid-import

STL 实体导入：解析+分类+CSX 载荷（B3；一切失败 ok=False 不抛出）。


## rfauto port-gate

端口尺寸收敛前置门（合成回放 JSON 面；防 #191/#254 浪费求解席位）。


## rfauto lint

设计体检一次查：约束/bounds/DFM/PDN/stub 聚合面（JSON 进出薄壳）。


## rfauto pool-patrol

池登记项新鲜度巡检（Z-11）：commit-tag×代码面双判据+撞号二次消歧。


## rfauto design-report

生成设计回放与总结报告（六节+扩展节 md 单文件，全数字带 provenance）。


## rfauto models

模型管理（EMSolver 可求解模型注册表；器件模板全目录见 template-spec list）

共 2 条叶子命令。

- `rfauto models list` — 列出已注册模型 + 可选导出参数 JSON Schema。
- `rfauto models docs` — 生成模型参数文档（Markdown，pydantic schema 自动推导）。

## rfauto jobs

任务管理

共 3 条叶子命令。

- `rfauto jobs status` — 查询任务状态 / 列出最近的 runs（SQLite 索引）。
- `rfauto jobs cancel` — 取消任务。
- `rfauto jobs watch` — 跟踪任务至终态（SN-19 --watch 泛化：CLI 轮询打点，零写入）。

## rfauto cache

缓存管理

共 1 条叶子命令。

- `rfauto cache clear` — 手动清理结果缓存。

## rfauto syn

微带线综合（E6a）

共 5 条叶子命令。

- `rfauto syn mline` — 微带线综合：目标阻抗 → 线宽（Hammerstad-Jensen + brentq 反解）。
- `rfauto syn wilkinson` — Wilkinson 功分器综合：f0 + Z0 → arm_len + series_w + shunt_w + 配方草稿。
- `rfauto syn branchline` — Branchline coupler 综合：f0 + Z0 → arm_len + series_w + shunt_w + 配方草稿。
- `rfauto syn patch` — 矩形贴片天线综合（Hammerstad 模型）：f0 + er + h → patch_len + patch_w + feed_offset。
- `rfauto syn bpf` — C13 带通滤波器综合：广义切比雪夫 → Cameron N+2 耦合矩阵 → folded/arrow。

## rfauto budget

链路预算（E8c）

共 1 条叶子命令。

- `rfauto budget run` — 链路预算：Friis 噪声级联 + 增益/P1dB 预算。

## rfauto cascade

系统级级联预算+混频杂散搜索（DP-5）

共 3 条叶子命令。

- `rfauto cascade budget` — 级联预算：增益/Friis NF/IIP3·OIP3 级联/P1dB(经验幂和)/噪声底/SFDR/灵敏度。
- `rfauto cascade spur` — 混频杂散落带搜索：f_spur=|m·f_RF±n·f_LO| 枚举 + 矩形卷积落带判定。
- `rfauto cascade plan` — IF 频率规划扫掠：候选 IF 逐点杂散判定 → spurious-free 窗口表。

## rfauto array

阵列/相控阵两档方向图引擎（DP-4：快速档单元×AF；互耦档 P3 接口预留）

共 3 条叶子命令。

- `rfauto array synthesize` — 闭式加权综合 + 快速档放行门（tier_gate：间距/扫描/栅瓣/耦合）。
- `rfauto array pattern` — 单扫描角阵列方向图（快速档=单元×AF 复域逐点乘 + Γ_act/Z_scan/盲点）。
- `rfauto array scan` — θ 扫描扫掠：逐点 tier 门 + Γ_act + 盲点旗（盲点筛查主口径）。

## rfauto diagnose

耦合矩阵/Q 诊断三件套（DP-2，JSON 进出薄壳）

共 5 条叶子命令。

- `rfauto diagnose q` — Q 双通道（VF 极点法 × Kajfez 圆拟合）互证 + skrf 第三方仲裁。
- `rfauto diagnose cm` — CM 反向提取（VF 结构面 + LM 固定拓扑精化）+ 可选目标逐元素偏差表。
- `rfauto diagnose cat` — Dishal 顺序调谐 critique（τ 峰数指纹 + issues + typed fixes）。
- `rfauto diagnose deviation` — 实测↔仿真偏差归因桥（FSV/相关性→四段式侦探叙事）。
- `rfauto diagnose detective` — 数据侦探四段式报告（发现/根因假设/证据链/结论；--run-dir 或 --ref 二选一）。

## rfauto anchors

物理标定锚注册表（DP-3，JSON 进出薄壳）

共 5 条叶子命令。

- `rfauto anchors list` — 列出全部已登记锚（DP-3 注册表 knowledge/anchors.yaml）。
- `rfauto anchors inspect` — 单锚全量记录（含 provenance/uncertainty/domain/consumers）。
- `rfauto anchors validate` — 校验注册表：schema + provenance 可解析 + 单源计数核对（DP-3 判据 3）。
- `rfauto anchors stale` — 锚新鲜度报告（QW-3）：last_verified 龄期 + stale 判定。
- `rfauto anchors drift` — 锚漂移预警（QW-16）：Mann-Kendall 趋势 + 分布指纹差分。

## rfauto surrogate

代理模型离线分析（E3）

共 3 条叶子命令。

- `rfauto surrogate analyze` — 离线 GP 代理模型分析：参数重要度 + 拟合误差（不进在线调优路径）。
- `rfauto surrogate uq` — 代理免费蒙特卡洛 UQ：良率 + 指标分布 + 敏感性排序（阶段 6.4）。
- `rfauto surrogate export-onnx` — torch 系代理（fno/deep_ensemble/siren）现场重拟合并导出 ONNX。

## rfauto runs

run 历史对比

共 10 条叶子命令。

- `rfauto runs compare` — 对比多次 run 的指标与 cost。--provenance 输出环境指纹复现块。
- `rfauto runs health` — 对单次 run 做求解健康度体检（G11：历史踩坑教训内核化）。
- `rfauto runs verify` — run 产物新鲜度校验：manifest 收官指纹 vs 盘上 Touchstone。
- `rfauto runs diff` — 双 run 深度只读对比（配置递归 diff+指标 Δ+S 曲线+判读提示）。
- `rfauto runs compare-batch` — 多 run 并排对账表（战役收官快速对账，W8-S4）。
- `rfauto runs watch` — 跟踪 run 至终态（SN-19 --watch 泛化：CLI 轮询打点，零写入）。
- `rfauto runs monitor` — run 目录周期体检（进度/截断嫌疑/NrTS 触顶/能量停滞四类时序判据）。
- `rfauto runs retrieve-similar` — 检索式 warm-start 先验（DA-2 k-NN 元特征相似检索，确定性零学习）。
- `rfauto runs stats` — runs 总览统计：总数、按 model/adapter/status 分组计数、最近 10 条。
- `rfauto runs export-tracking` — run trials 单向导出为 MLflow 目录 + W&B JSONL（G10；校验先于写入）。

## rfauto datasets

数据集注册表 v2（runs 点级数据 → Parquet + SQL 查询）

共 9 条叶子命令。

- `rfauto datasets materialize` — 把 runs/ 点级数据物化为 Parquet 数据集（指纹去重 + manifest 落盘）。
- `rfauto datasets query` — DuckDB 直查 Parquet 数据集（谓词下推/列裁剪，where 经白名单校验）。
- `rfauto datasets profile` — 数据集一键画像（audit 席快速画像，W8-S4）。
- `rfauto datasets discover-workdir` — 发现工作目录形态真机产物（无 meta.json 的 runs 子目录，只读）。
- `rfauto datasets import-workdir` — 工作目录形态真机产物导入数据集注册表（无 meta.json 的漏数口）。
- `rfauto datasets coverage` — 数据集覆盖度：点数分布 + 参数空间逐维占用率/最弱维（WP2.4①）。
- `rfauto datasets annotate` — ground truth 标注（白名单通道）+ 6.3 解锁进度（幂等回写 manifest）。
- `rfauto datasets visibility` — 公开/私有双集切换（public 是 HF 导出放行前提；manifest 回写）。
- `rfauto datasets export-hf` — HF datasets 本地目录布局导出（parquet 分片 + README 数据卡，确定性逐字节一致）。

## rfauto agent

Agent 提案/执行编排（E4b 三层 Gate）

共 2 条叶子命令。

- `rfauto agent propose` — 提案模式：L1/L2 Gate 校验 + L3 确认 token（不执行）。
- `rfauto agent apply` — 执行模式：校验 token 后真实运行（参数被篡改会被哈希校验拒绝）。

## rfauto kicad

KiCad 板级链路（E7a：P-Cell 生成 + DRC gate）

共 6 条叶子命令。

- `rfauto kicad design-from-run` — run 最优参数→PCBDesign JSON 草稿桥（SO §6③ A8；接 kicad pcb→drc 链）。
- `rfauto kicad pcb` — 从 JSON 设计描述生成 KiCad PCB（子进程调用 KiCad Python 3.11）。
- `rfauto kicad drc` — KiCad DRC/RF 规则门禁（errors 阻断，warnings 告警）。
- `rfauto kicad extract` — 从 .kicad_pcb 提取叠层/走线/过孔/板框/zone/footprint（B6 stage-2，子进程 KiCad Python）。
- `rfauto kicad gerber` — KiCad 板 → Gerber X2 + Excellon 制造交付包导出（LC-1，子进程 KiCad Python）。
- `rfauto kicad optimize` — PCB 提取 → CPWG 闭式代理寻优环（|z0−target|≤tol 判据；FAIL 附确定性修正 w*）。

## rfauto recipe

配方版本管理（方向 7）

共 3 条叶子命令。

- `rfauto recipe migrate` — 迁移配方到当前版本（添加 recipe_version 字段）。
- `rfauto recipe skill` — 配方 → agent skill（SKILL.md + frontmatter，阶段 2.4）。
- `rfauto recipe diff` — 两版配方/设计声明的逐键差异（SN-15；数值键带相对变化，铁律 7 零新数值）。

## rfauto chain

有源链路分析（C14：LNA 匹配链 / PA load-pull 口径）

共 2 条叶子命令。

- `rfauto chain lna` — LNA 匹配链端到端：ADS 联合 vs 手工口径+稳定性+噪声（真机面）。
- `rfauto chain loadpull` — PA load-pull 口径：Cripps 等功率圈全离线分析（零仿真零 license）。

## rfauto study

人机参数注入研究（方向 6a/4d）

共 1 条叶子命令。

- `rfauto study inject` — 向 Optuna study 注入人工参数（ask-and-tell）。

## rfauto solvers

求解器管理（方向 6g/6h）

共 4 条叶子命令。

- `rfauto solvers list` — 列出已注册求解器及其可视化能力（方向 6g/6h）。
- `rfauto solvers viz` — 列出求解器可视化产物声明（方向 6g 产物视图协议）。
- `rfauto solvers add` — 添加求解器到 configs/solvers.yaml（方向 6h）。
- `rfauto solvers qucsator-mline` — qucsatorRF mline 名义点三方 β 对照（qucsator/openEMS 金锚/HJ；DP-14 N7）。

## rfauto calc

微波闭式计算器（E4：mm/GHz/Ω/dB 口径）

共 2 条叶子命令。

- `rfauto calc list` — 列出全部计算器与参数表（实验键带【实验】标签，运行需 --allow-experimental）。
- `rfauto calc run` — 执行计算器。

## rfauto vna

VNA 测量闭环（DP-11：En 相关性报告 + 离线回放）

共 4 条叶子命令。

- `rfauto vna en-report` — En 计量学相关性报告（|En|≤1 满意；深谷自动切线性域，#370/#371）。
- `rfauto vna replay` — VNA 离线回放回归（mock 仪表 采集→校准→相关 全链，零硬件）。
- `rfauto vna measure` — VNA 测量采集 run（真机 opt-in：无 --address 时只出 dry-run 计划信封）。
- `rfauto vna calibrate` — 独立软件校准/去嵌（SOLT/TRL/multiline 全方法，零硬件零连接）。

## rfauto oracle

闭式预言机（QM-2 生成式对拍，只读查询面）

共 3 条叶子命令。

- `rfauto oracle list` — 列出全部已注册闭式预言机（键/kind/覆盖键/闭式源/域盒声明）。
- `rfauto oracle check` — 单键生成式对拍（注册计算器输出 vs 闭式期望，网格逐点 A/B/C/D 分级）。
- `rfauto oracle check-all` — 全注册 oracle 生成式对拍总报告（覆盖键数 + 分级统计 + D 级旗标）。

## rfauto bench

AgentBench/goldset 回归门（WP3.7/F6）——离线、确定性、零网络

共 6 条叶子命令。

- `rfauto bench goldset` — 工具调用层金标回归门（runtime/协议变更后一键回归）。
- `rfauto bench agentbench` — AgentBench 智能体基准回归门（两轴打分 + 公开/私有双集防污染）。
- `rfauto bench level2` — §10.10 Level 2 端到端门：10 句 NL 设计任务成功率 ≥7/10 + 七环节覆盖矩阵。
- `rfauto bench prompt-regression` — 系统提示词 A/B 回归门（AD-1 §D-4）：两版 prompt × 公开 goldset 四指标差分。
- `rfauto bench consistency` — pass^k × 成本一致性评测门（AD-4）：每任务多次独立 trial 的无偏
- `rfauto bench netlist-goldset` — 网表 goldset 回放门（AI-6/F-10 批B）：注入 qucsatorRF 真通道逐任务回放对照 gold 值。

## rfauto bands

标准频段/环境包络注册表（D9，十接口；数值只出自 core/bands 常量表）

共 10 条叶子命令。

- `rfauto bands list` — 列出标准频段注册表（3GPP/Wi-Fi/UWB/ISM/EMC 等，自动生成清单）。
- `rfauto bands get` — 按 key 取单条频段详情（边界/出处/区域）。
- `rfauto bands find` — 查包含给定频率的全部频段条目。
- `rfauto bands spec-bounds` — 频段键 → SpecEvaluator band 结构（f_low/f_high 二元组，喂 objectives）。
- `rfauto bands env-list` — 列出环境包络注册表（工业/AEC-Q100/ECSS/IEC 60068 温区等级）。
- `rfauto bands env-get` — 按 key 取单条环境包络详情（温区/等级/出处）。
- `rfauto bands env-find` — 查温区覆盖给定温度的全部环境包络。
- `rfauto bands env-delta-t` — 环境包络 → ΔT 上下限（D3 温区扫描 / D8 UQ / WP4.2 良率消费）。
- `rfauto bands env-uq-axis` — 环境包络 → UQ/良率温度轴（名义点 + σ + ΔT 上下限）。
- `rfauto bands env-points` — 环境包络温区等距采样点（供 D3 温区扫描）。

## rfauto campaign

战役状态机（calibrate→prefilter→tune→tolerance→report→final_verify）

共 7 条叶子命令。

- `rfauto campaign plan` — 配方 → 确定性战役阶段队列（含依赖/预算/license 门槛）；--out-dir 落盘。
- `rfauto campaign status` — 读回已落盘战役计划的状态（verdict/各阶段 status/n_done/n_dead）。
- `rfauto campaign event` — 推进战役状态机（stage_failed 时依赖它的未完成阶段递归 aborted）并回写落盘。
- `rfauto campaign list` — 扫 root 下全部已落盘战役计划（总览）。
- `rfauto campaign run` — 一键闭环执行战役计划（calibrate→…→report→final_verify；断点续跑内嵌）。
- `rfauto campaign digest` — 扫描战役终态（COMPLETE/PARTIAL/ABORTED）聚合成 zh 人读摘要，JSON+文本产物落 runs/ 下。
- `rfauto campaign queue-daemon` — campaign 排队常驻执行体：轮询队列→依赖检查→日历窗→license 预检→逐项启动（启动后不等）。

## rfauto template-spec

模板库 TemplateSpec 注册表（E2：清单 + 综合草稿）。语义区别：此处=器件模板全目录（渲染/综合/fake/HFSS 组件齐备性台账）；rfauto models list=已接入求解通道的可求解模型（配方 model 键取值）。

共 3 条叶子命令。

- `rfauto template-spec list` — 列出全部模板 spec（组件齐备性 render_script/synthesizer/fake_model/hfss_plugin）。
- `rfauto template-spec draft` — 按模板 spec 的综合入口产出配方草稿（零求解、零 license；线宽等由综合内核精算）。
- `rfauto template-spec recommend` — 按指标查询推荐模板（确定性 filter+rank，零 LLM 零物理数字产出）。

## rfauto uq

公差/良率收口（WP4.2：名义点良率 / 设计中心化 / D9 温区良率）

共 4 条叶子命令。

- `rfauto uq yield-at` — 显式名义点的代理蒙特卡洛良率（良率目标函数点值形式）。
- `rfauto uq design-center` — 良率目标函数 + 设计中心化（容差盒网格违约 cost≤0 良率，坐标搜索；MC 只做前后认证）。
- `rfauto uq temp-zone` — 温区良率（D9 环境包络 → 温度轴 σ 并入 MC + 温区两端角点确定性评估，FAIL 如实）。
- `rfauto uq robustness` — 稳健性报告：良率 MC（向量化）+FORM Pf+worst-case 角点+逐规范 Cpk（DP-15 C3）。

## rfauto farfield

远场方向图/增益/效率/SAR（WP4.1 nf2ff 产物视图）

共 2 条叶子命令。

- `rfauto farfield list` — 含远场/SAR 产物的 run 清单。
- `rfauto farfield view` — 单 run 远场视图：φ 切面 θ-dB 序列 + Dmax/效率/HPBW/F/B + SAR（core/farfield 确定性解析）。

## rfauto rationale

设计理由/经验记忆（F11 typed 经验检索 + F2 runs 理由语料 TF-IDF）

共 3 条叶子命令。

- `rfauto rationale recall` — 任务描述 → 命中历史坑/核对表/动作（确定性关键词匹配，无 embedding/网络）。
- `rfauto rationale checklist` — 冒烟前核对表门禁：模板名 → 核对表 + gate（命中即要求先离线审计），可嵌入任务书。
- `rfauto rationale search` — runs/ 产物理由语料 TF-IDF 余弦检索（为什么这么做：autotune issues/fixes/meta）。

## rfauto rag

RAG 知识库词法检索（BM25，只读、citation 可溯）

共 3 条叶子命令。

- `rfauto rag index` — 构建 RAG 索引并输出统计快照（JSON 直出，零写副作用）。
- `rfauto rag query` — RAG 检索（JSON 直出：hits + citation + snippet，只读）。
- `rfauto rag explain` — RAG 检索 + 逐词 BM25 分数明细（tf/df/idf/contribution，打分可溯）。

## rfauto self-heal

自愈环只读诊断（F5：日志面→确定性 critique→根因/建议）

共 1 条叶子命令。

- `rfauto self-heal run` — 对既有 run 跑一次只读自愈环（零真机；只诊断+建议，不自动改配方）。

## rfauto logs

日志语义蒸馏（LogDistiller：stdout/审计 JSON→结构化 digest）

共 1 条叶子命令。

- `rfauto logs digest` — 日志 → 结构化 digest（rc/errors/warnings/指标/失败签名；只读不落文件）。

## rfauto materials

材料库工具（D1 色散适应性报告；只读）

共 1 条叶子命令。

- `rfauto materials dispersion-report` — 材料在频带内的色散适应性报告（εr/tanδ 漂移 + 常数近似判定 + 修正建议）。

## rfauto pcell

PCell 参数化单元 DSL（LC-2 复活：库清单/定义/求值/渲染 Layout 出口）

共 4 条叶子命令。

- `rfauto pcell list` — 列出 PCell 库：单元名/参数边界/原语构成（3 迁移模板 + LC-2 新单元）。
- `rfauto pcell show` — 显示 PCell 定义（DSL 文本面：参数/派生量/原语声明/内核名）。
- `rfauto pcell eval` — 求值 PCell：参数点 → 原语几何（JSON 进出；数值全出确定性内核）。
- `rfauto pcell render` — 渲染 PCell → Layout（求值产物直产）→ 可选 GDSII/DXF/IPC-2581/ODB++ 导出。

## rfauto db

注册表数据库（SQLite 事务型注册表 + DuckDB 分析直读；零服务器）

共 8 条叶子命令。

- `rfauto db init` — 建库 + 幂等迁移（首次 applied=1，重放 applied=0）。
- `rfauto db migrate` — 执行幂等迁移（schema_version 表递增；重复执行零变更）。
- `rfauto db status` — 注册表状态：路径/存在性/schema 版本/各表行数（文件不存在不创建）。
- `rfauto db reindex-runs` — 扫 runs/*/meta.json 重建 runs 表（upsert 幂等；单文件失败不阻塞 #105）。
- `rfauto db query` — 只读查询注册表（SELECT 白名单 + 参数绑定；拒绝原因进信封）。
- `rfauto db analytics-attach` — DuckDB sqlite 扩展直读注册表（零拷贝分析面；不可用如实 ok=False）。
- `rfauto db league-rebuild` — 引擎联赛表重建（DP-17 W1：verdict 形态白名单抽取，幂等）。
- `rfauto db league-report` — 联赛报告：按（族，量）出 |delta| 中位×wall_s 中位 Pareto 前沿（JSON+md 双出）。

## rfauto slotline

槽线闭式（Janaswamy–Schaubert 1986：分析/综合；越有效域拒绝不外推）

共 2 条叶子命令。

- `rfauto slotline analyze` — 槽线闭式分析：(w, h, εr, f) → Z0、εeff、β、λ'（越有效域拒绝不外推）。
- `rfauto slotline synth` — 槽线综合：目标 Z0 → 槽宽 w（窄槽段括号反解；不可达如实 realizable=False）。

## rfauto transitions

MSL↔槽线过渡与 Marchand 巴伦设计（微带 HJ 综合 + 槽线闭式精算）

共 3 条叶子命令。

- `rfauto transitions msl-slot` — Roberts/Knorr MSL↔槽线过渡设计参数（开路支节 λg/4+Δl、槽线短路臂 λg'/4）。
- `rfauto transitions marchand-balun` — 双槽臂 Marchand 巴伦设计参数（d_c=w_msl+s_slot；在过渡参数上补槽距与 a1/a2）。
- `rfauto transitions marchand2` — 两节对称 Marchand 电路级综合（KJ 几何反解 + 电路级自检门；不可达如实 realizable=False）。

## rfauto reports

双输出报告链（DP-13 U1：run → 同一报告模型双出 PDF+HTML）

共 2 条叶子命令。

- `rfauto reports render` — 渲染 run 报告：同一报告模型（rfauto-report/v1）双出 typst PDF + plotly 自包含 HTML。
- `rfauto reports run-figures` — HFSS run 四联图：S 参数幅值+相位+群时延+εeff 一张 PNG（反馈 P2）。

## rfauto mmt

RWG/SIW 模基 MMT 求解（DP-1：段表 mm + 频网 → 50Ω S 参数，秒级零外部进程）

共 1 条叶子命令。

- `rfauto mmt solve` — MMT 段表求解（JSON 进出薄壳，零逻辑转发 mmt_service.solve_mmt）。

## rfauto nfmeas

近场测量变换与 .ffs 视图（DP-18 C10a）

共 2 条叶子命令。

- `rfauto nfmeas ffs-info` — 审计 .ffs 头（频率/三功率/网格规模），不落全量复矩阵。
- `rfauto nfmeas nf2ff` — 平面近场 2D 复场 → 远场方向图（dB 归一 JSON）。

## rfauto nfc

NFC/WPC 平面螺旋线圈闭式（DP-18 C10b）

共 3 条叶子命令。

- `rfauto nfc evaluate` — Mohan 三式电感评估（nH/μm 输入口径）。
- `rfauto nfc synth` — 目标电感 → 外径反解（二分 + 回代自洽）。
- `rfauto nfc q` — 有载/无载 Q 报告面（互感 T 模型精确式）。

## rfauto sar

SAR 合规后处理（DP-18 C10c）

共 1 条叶子命令。

- `rfauto sar report` — 1g/10g 立方平均 + 峰值定位 + 分布（62704-1 简化档，coverage 如实）。

## rfauto si

SI 通道报告（df7 T2：无源性/因果性/TDR/COM，纯后处理）

共 2 条叶子命令。

- `rfauto si report` — SI 通道一键报告（JSON 进出薄壳；COM 段 4 端口文件可用，缺装如实降级）。
- `rfauto si mixed` — 混合模 S 参数指标（QW-1：skrf se2gmm 薄封装；差分插损/回损/共模/模式转换）。

## rfauto lake

runs/ 湖索引与分层压实（df7 F3：DuckDB 索引 + tar.zst 内容寻址归档）

共 10 条叶子命令。

- `rfauto lake index` — 扫 runs/ 重建 DuckDB 湖索引（幂等重建；缺失字段如实 NULL 不臆造）。
- `rfauto lake query` — 湖索引只读查询（等值过滤+日期段；JSON 进出走 service，值只进 ? 绑定）。
- `rfauto lake pack` — 战役目录 → tar.zst + 偏移清单（确定性排序+归一化头，内容寻址锚）。
- `rfauto lake verify` — 归档校验：整包 sha256 快校验 + 逐文件 sha256 重算（如实逐文件报告）。
- `rfauto lake restore` — 恢复归档到新目录（目标已存在即拒；拒绝覆盖语义由 service 透传）。
- `rfauto lake sweep` — incomplete/半产物只读清点报告（QW-13；DP-9 的 gc 视角，零改写）。
- `rfauto lake export-parquet` — 湖索引表→parquet 冷层（P-5 COPY PARTITION_BY 接口；外部引擎直读）。
- `rfauto lake audit-stale` — 扫全湖产出将失效 run 清单与原因分类（code/params/engine/env/budget）。
- `rfauto lake lineage` — 跨 run 血缘查询：数据集到上游 run 到渲染 commit 端点，或反向影响面。
- `rfauto lake compact` — 湖语义压缩规划与执行：h5 白名单保留+et/ht 去重（缺省 dry-run 纯读）。

## rfauto constraints

渲染前声明式几何约束检查（R4：z3 一次求解，UNSAT 冲突组+witness）

共 1 条叶子命令。

- `rfauto constraints check` — 渲染前一次求解：约束配置 → verdict+冲突规则（JSON 进出薄壳）。

## rfauto pdn

PI/PDN AC 阻抗域分析（F-B：目标阻抗/去耦选型/平面腔模门）

共 3 条叶子命令。

- `rfauto pdn analyze` — PDN 阻抗谱分析：Z 谱+逐频裕量+反谐振峰清单+腔模（JSON 进出薄壳）。
- `rfauto pdn select` — 贪心 decap 选型：candidates+budget+target → 选中明细+逐频裕量（infeasible 如实透传）。
- `rfauto pdn gate` — KiCad AC-PI 门：平面腔模筛查+安装避让+（可选）Z 谱裕量门（verdict 三值）。

## rfauto aging

器件老化漂移（F-C：PoF 时间轴→εr 漂移→EOL 失谐判据，fake 通道）

共 3 条叶子命令。

- `rfauto aging simulate` — 老化漂移仿真：任务剖面→εr 漂移轨迹→fake 名义/EOL 两点 S 参数+失谐量。
- `rfauto aging verdict` — EOL 失谐判据：|detune_pct| ≤ spec（恰等判 PASS）→ PASS/FAIL 纯确定性。
- `rfauto aging report` — 老化报告：mission_profile 表/漂移轨迹/EOL 判据/法源 provenance 四节。

## rfauto afs

AFS 自适应频扫（M-3：向量拟合驱动选频点，收敛即停；JSON 进出薄壳）

共 2 条叶子命令。

- `rfauto afs plan` — AFS 扫频计划（纯计划面：初始频点表+加密协议+验收判据，不求解）。
- `rfauto afs sweep` — AFS 自适应频扫端到端演示（--synthetic 合成多谐振函数当真响应，零真机）。

## rfauto interop

Touchstone 互操作（ME-10'：TS 2.1 写出 + HFSS 注释块直读）

共 2 条叶子命令。

- `rfauto interop ts21-write` — Touchstone 2.1 写出：skrf 原生 2.1 关键字 + provenance 注释块 + 读回对拍。
- `rfauto interop hfss-comments` — HFSS Touchstone 注释块直读：Gamma 传播常数 + Zpi 端口阻抗（模态基）。

## rfauto fab

HFSS → 可机加交付包（STEP/x_t + DXF 图 + 审计门禁，T43）

共 11 条叶子命令。

- `rfauto fab go` — 一键交付包：--vars 离线链 / --project 真机链（自动审计，FAIL 禁发图）.
- `rfauto fab pipeline` — 离线端到端轻量链：vars → dims → 轮廓/图纸 DXF → 审计 → 打包.
- `rfauto fab snapshot` — 变量 JSON → dims.json（单位强制 mm，raw 字符串保真）.
- `rfauto fab draw` — dims.json → GB 图框 DXF 图纸（标注值只取 dims，禁止测量回填）.
- `rfauto fab audit` — A1–A12 审计门禁（FAIL=退出码 1，禁止发图）.
- `rfauto fab pack` — 组装交付目录（manifest+哈希+审计报告；audit FAIL=退出码 1）.
- `rfauto fab rules` — 显示工艺公差规则库（公差类/审计阈值/表面处理）.
- `rfauto fab catalog` — 波导(WR/BJ)/法兰/嘉立创配合带/Kerr 规则标准库目录.
- `rfauto fab export` — 连接 HFSS 导出 x_t/step + dims 快照（需 rfauto（hfss extra）+AEDT）.
- `rfauto fab parse` — Gerber 光绘结构化解析（指令级+几何落地面；配 drill 时加跑交叉校验）.
- `rfauto fab summary` — Gerber 层摘要（按 D 码分组计数+aperture 类型统计+包络盒）.

## rfauto remote

多机协同仿真资源（探活/状态；v0：HFSS gRPC 远程会话+SSH 通道）

共 5 条叶子命令。

- `rfauto remote probe` — TCP 探活登记机器（SSH/许可/RDP 端口连通性+时延，零副作用零凭据）。
- `rfauto remote status` — 探活 + SSH 认证可达性（凭据缺失如实 missing_credentials 不猜不试）。
- `rfauto remote resources` — 并发求解面资源视图（本机 openEMS/HFSS 进程互斥态+服务器可达/在跑/磁盘）。
- `rfauto remote queue` — 任务队列视图（job_registry 在途作业+单写锁排队+席位占用+服务器在跑态）。
- `rfauto remote board` — 服务器队列看板：机器表+队列任务表+互斥状态+异常降级行单快照。

## rfauto stats

量产统计三件套（保护带/能力指数/Weibull 寿命，§B-5）

共 3 条叶子命令。

- `rfauto stats guardband` — 保护带接受限与判定（ILAC-G8：AL=TU−w、w=m·U、m=z_{1−PFA}/k）.
- `rfauto stats cpk` — Cp/Cpk/Ppk 点估计+置信区间（σ̂=s/c4(n)；Cpk CI=Bissell 1990 近似）.
- `rfauto stats weibull` — 右删失 Weibull MLE（scipy CensoredData；Fisher/LR 双口径区间+B10 下限）.

## rfauto firmware

固件工件三出口（波束码字/变容管 DAC/DPD 定点，§B-6）

共 3 条叶子命令。

- `rfauto firmware beam` — 波束码字表：目标相位→b-bit 码字，CSV+C 头双出+回代判据审计.
- `rfauto firmware varactor` — 变容管 DAC 偏置表：f→C→V→码，单调性审计+饱和计数.
- `rfauto firmware dpd` — DPD 定点表：Q 格式定标+舍入回代预检（NMSE ≤0.5dB 劣化门）+溢出告警.

## rfauto preflight

XC-F 开工前统一预检（极限/功率/热/加工/精度档案五门联合）

共 2 条叶子命令。

- `rfauto preflight run` — 五门联合预检；verdict=issues 时退出码 1（拦截语义）。
- `rfauto preflight gates` — 列出门名与缺省顺序（零 payload 只读面）。

## rfauto profile

剖析入口（PR-8）：py-spy 火焰图落 runs/（py-spy 为可选依赖）

共 2 条叶子命令。

- `rfauto profile status` — py-spy 可用性探测（JSON 信封；未装=available=false+安装提示）。
- `rfauto profile run` — py-spy record 封装：采样落盘 runs/（火焰图 .svg 浏览器直接看）。

## rfauto layout

版图家族（生成与互操作、装配、diff、LVS、拼板、仿真组装、钢网、STEP）

共 8 条叶子命令。

- `rfauto layout build` — 版图生成与互操作四模式：生成（--kind）、导出（--from-payload）、读入（--import-file）、往返报告（--round-trip）。
- `rfauto layout assemble` — KiCad 子进程装配导出：放置表 .pos 与聚合 BOM CSV（铁律 2 子进程域）。
- `rfauto layout diff` — 两份版图载荷三面语义 diff：层、图元、端口（端口面 opt-in）。
- `rfauto layout lvs` — 几何网表对照参考连接表（flag 级）；判定 LVS_FLAG 时退出码 1。
- `rfauto layout panelize` — 拼板闭式：板阵列尺寸、V 槽或邮票孔分板规格、利用率、基准标记。
- `rfauto layout simulate` — 版图 openEMS 渲染脚本离线组装（零求解；产物=渲染脚本，--out-dir 落盘）。
- `rfauto layout stencil` — 钢网开孔 IPC-7525 双判据批量评估：面积比与宽厚比逐孔加汇总。
- `rfauto layout step` — KiCad 板级 STEP 导出子进程面；缺 kicad-cli 走 skipped 信封（不报错）。

## rfauto teaching

模板教学卡（物理推导+敏感性排序+教科书索引）

共 2 条叶子命令。

- `rfauto teaching show` — 教学卡全文：物理与推导 + 敏感性排序（缺卡/缺块显式报错不硬凑）。
- `rfauto teaching index` — 教科书反向索引：章节↔模板↔内核模块对照（零过滤命中=空表如实）。

## rfauto zenodo

Zenodo 元数据导出与 CITATION.cff 校验（PR-11，零网络）

共 2 条叶子命令。

- `rfauto zenodo export` — CITATION.cff → Zenodo deposit 元数据（纯本地组装，零网络）。
- `rfauto zenodo validate` — CITATION.cff 校验（必填字段+pyproject 版本同步；warnings 不判失败）。

## rfauto few-shot

成功会话 few-shot 精选（AD-3：挖掘→精选→注入节）

共 1 条叶子命令。

- `rfauto few-shot build` — 挖掘成功会话 → 相关性精选 top-k → 系统提示词注入节（零网络）。

## rfauto hints

错误提示规则面（错误指纹 → 可行动提示，只读）

共 1 条叶子命令。

- `rfauto hints list` — 列出全部错误提示规则（指纹/提示/坑号指针/级别，确定性序）。

## rfauto pitfalls

坑账检索面（AGENTS.md 踩坑速查全量索引，只读）

共 2 条叶子命令。

- `rfauto pitfalls search` — 坑账关键词检索（确定性词面计分：头部命中 2 分/全文 1 分）。
- `rfauto pitfalls get` — 按 id 精确查坑（未命中 → error 信封退出码 1，不抛穿）。

## rfauto dag

DAG 执行基座（断点续跑/CAS/watchdog/#261 互斥；pipeline.dag_runner）

共 2 条叶子命令。

- `rfauto dag run` — 执行 DAG 计划（断点续跑内嵌；solve 节点过 #261 机器互斥）。
- `rfauto dag status` — 状态期刊节点态摘要（与 journal 一致；done/failed/inconclusive 等）。

## rfauto anim

动图渲染（typed spec JSON→SVG 动画；service.animation 内核）

共 1 条叶子命令。

- `rfauto anim render` — 渲染动图 SVG（确定性：同 spec 两跑逐字节同，sha256 钉）。

## rfauto vendor-docs

厂商帮助文档检索（FTS5 索引+带引用检索+零入库审计）

共 3 条叶子命令。

- `rfauto vendor-docs build` — 构建厂商文档 FTS5 索引（增量 sha256 去重；rebuild 全量重建）。
- `rfauto vendor-docs search` — 带引用检索（FTS5 trigram MATCH→短词 LIKE 回退；引用含 source/
- `rfauto vendor-docs audit` — 索引库零入库审计（记录数/chunk 字符总量/来源清单——红线复核面）。

## rfauto fault-tree

故障树分析（QM-FTA：playbook→OR-of-AND 树+最小割集+Mermaid 图）

共 1 条叶子命令。

- `rfauto fault-tree report` — 故障树报告（复合叶）：树构建+最小割集单次产出，--format mermaid 附图文本。

## rfauto datasheet

器件 datasheet 生成（EP-4：run 报告/模板名义 → 规格书 md/HTML）

共 1 条叶子命令。

- `rfauto datasheet build` — 构建器件规格书（复合叶）：build_datasheet+render_markdown/html 单次产出。

## rfauto humidity

湿度吸湿漂移（F-H.2：Fick 吸湿估计+MSL 车间寿命查询）

共 2 条叶子命令。

- `rfauto humidity uptake` — 湿度吸湿端到端估计：Fick 级数+短时 √t 律双路径+可选 εr(M) 混合节。
- `rfauto humidity msl` — MSL 车间寿命查询：J-STD-033 表+可选 exposure_h 耗尽判定。

## rfauto weave

玻纤编织 skew（HS-1：样式表查询+最坏/期望 skew 估计）

共 2 条叶子命令。

- `rfauto weave styles` — 编织样式表查询（零 payload 只读面，preflight gates 先例）：参数+MIT 出处。
- `rfauto weave estimate` — 编织 skew 端到端估计：样式→εeff 界→最坏/期望 skew→zigzag 残余→UI verdict。

## rfauto cryo

低温材料面（F-H.4：铜面全量+可选超导节/Q 分解估计）

共 1 条叶子命令。

- `rfauto cryo surface` — 低温材料面端到端估计：铜面必出；超导节/Q 节可选（键透传）。

## rfauto goal

持久目标（用户 Goal 工作模式：跨重启存续+自动续轮，DS-3）

共 4 条叶子命令。

- `rfauto goal set` — 立持久目标（跨重启存续；幂等同 id 覆盖）。
- `rfauto goal status` — 目标状态（objective/判据/轮次/历史摘要，跨进程存续读回）。
- `rfauto goal advance` — 推进一轮（确定性状态机：done/advancing/blocked 三态；零模型轮）。
- `rfauto goal list` — 清点全部持久目标（只读摘要）。

## rfauto dev

维护者脚手架（骨架生成+消费钉清单，SO §7 P5）

共 2 条叶子命令。

- `rfauto dev new-template` — 新模板骨架包：meta 草稿+渲染/审计占位+消费钉清单（不覆盖既有）。
- `rfauto dev new-calculator` — 新计算器骨架：注册占位+消费钉清单（不覆盖既有；骨架文件不入库）。

## rfauto design

level2 设计链（NL 意图→族路由→综合→kickoff 草稿→闭环）

共 2 条叶子命令。

- `rfauto design kickoff` — 设计 kickoff：意图→族路由→闭式综合→离线评→bounds/objectives 配方草稿。
- `rfauto design close` — 设计闭环：certify → 锚回写草稿 → replan（单步失败不拖垮其余）。

## rfauto sandbox

agent 配方沙箱治理（草稿列表/差异/三层 Gate 提案）

共 3 条叶子命令。

- `rfauto sandbox list` — 列出沙箱草稿（含与真实配方的匹配 + 参数差异摘要）。
- `rfauto sandbox diff` — 查看单个沙箱草稿与真实配方的差异（unified diff+参数差异表）。
- `rfauto sandbox promote` — 草稿差异送三层 Gate（L1 白名单+L2 dry-run+L3 确认）——生成提案进收件箱。

## rfauto edb

EDB 快车道（PyEDB 建库+hfss_batch 批解，平面族发射器）

共 3 条叶子命令。

- `rfauto edb build` — 发射 spec + EDB 建库（pyedb configuration → .aedb 工程+存证）。
- `rfauto edb solve` — 批处理求解（ansysedt -BatchSolve）+ 可选 Touchstone 批后导出。
- `rfauto edb status` — 扫描产物根目录的快车道资产清单（工程/存证/日志/Touchstone）。

## rfauto recast

RECAST 判据重放（归档判读×现行判据确定性复算，只读）

共 2 条叶子命令。

- `rfauto recast status` — 判据注册面清单（每条 id/规则形态/装载状态；坏条目如实登记）。
- `rfauto recast replay` — 批量重放（全部已注册判据×全部证据，三向标注 same/flip/not_judged）。

## rfauto rest

REST 面 schema 导出（端点清单与 OpenAPI spec 机读出口，只读）

共 1 条叶子命令。

- `rfauto rest schema` — REST 全端点机器可读清单（程序化枚举路由表单源，防手抄漂移）。

## rfauto templates

模板 golden 几何回归仓（EC-8：渲染哈希+CSX 摘要逐族对比）

共 2 条叶子命令。

- `rfauto templates golden-diff` — 模板渲染产物 vs golden 快照逐族对比（脚本 sha256+CSX 几何摘要+网格）。
- `rfauto templates export-recipe` — 模板族 → 配方 YAML 一键导出（T-Q14 模板→配方通路单源）。

## rfauto em

自定义 EM 模型语义面：清单驱动的 pre-solve 体检、THRU 去嵌与指标提取（零 AEDT 依赖）、DOE/矩阵 sweep 编排（串行真机+资源闸）、run 目录级 diff 四面对比

共 5 条叶子命令。

- `rfauto em doctor` — EM 模型清单体检（16 项检查表中清单可判定的子集）。
- `rfauto em deembed` — THRU 对称半拆双边去嵌 + 串联指标提取（参考面从引线外端移回 pad 边缘）。
- `rfauto em metrics` — 串联/并联器件 C/R/Q 指标（强失配下拒绝简化式，用 Z12 传输阻抗）。
- `rfauto em sweep` — DOE/矩阵编排（16 组=2 器件 × 2 版本 × 4 厚度一条命令跑完）。
- `rfauto em diff` — run 目录级四面对比（替代手工 diff .aedt 文本）。

## rfauto mo

多目标寻优（MO-BO）：内置合成族环跑，EHVI 采集 + 超体积裁判，mt_gp 联合后验驱动

共 1 条叶子命令。

- `rfauto mo run` — 跑内置合成族多目标 BO 环：HV 曲线 + 帕累托前沿 + 采集轨迹。

## rfauto competition

单目标优化器族竞赛（T-N5 标量架）：多引擎同预算同 seed 组竞赛，最优值 AUC 两阶段排名 + 达标评估次数，报表落 md+json

共 1 条叶子命令。

- `rfauto competition run` — 跑单目标优化器族竞赛：三套排名 + 逐 run 明细，报表落 md+json。

## rfauto al

主动学习（AL）：小样本标注预算下提议下一批实验点（σ×距离双重准则或 T-N9 采集三族）

共 1 条叶子命令。

- `rfauto al propose` — 提议下一批实验点：读湖样本 → 不确定度×距离（或采集族）→ top-k。

## rfauto diagram

电路图绘制六叶（前五叶出原生可编辑 .drawio 工程图，算画同源；to-svg 出静态 SVG 看图件）：link=RF 链路框图（每级标增益/NF，Friis 级联内核单源）；testsetup=射频测试连接图（仪器卡+连线，标注=输入原值）；annotate=评审标注双层（底图锁定+三色意见栏）；stackup=PCB 叠层横截面（层带∝厚度，线宽可选综合单源）；schematic=引脚级原理图（ADS 网表，元件带引脚点+引脚到引脚连线+网名标注）；to-svg=.drawio→SVG 纯 Python 渲染（服务器/报告无 GUI 看图件，框+连线+文字坐标直映射，不支持样式降级占位+warnings）

共 6 条叶子命令。

- `rfauto diagram link` — 生成 RF 链路框图 .drawio：级表 → 原生可编辑工程图（每级标数字）。
- `rfauto diagram testsetup` — 生成射频测试连接图 .drawio：声明式场景 → 原生可编辑工程图
- `rfauto diagram annotate` — 生成评审标注双层 .drawio：底图+标注表 → 底图层锁定+标注层三件组。
- `rfauto diagram stackup` — 生成 PCB 叠层横截面图 .drawio：声明式叠层 → 原生可编辑工程图
- `rfauto diagram schematic` — 生成引脚级原理图 .drawio：ADS 网表 → 元件带引脚点+引脚到引脚
- `rfauto diagram to-svg` — 渲染 .drawio 为静态 SVG：mxGraph XML → 纯 Python SVG（服务器/报告

## rfauto ads-circuit

ADS 前仿链：参数化电路图 .drawio 出图/运行/反标注回路（draw.io Edit Data 改值 → hpeesofsim 前仿 → 指标反标注上图）

共 3 条叶子命令。

- `rfauto ads-circuit diagram` — J1 出图：族+SnP → 参数化电路图 .drawio（UserObject 三件组）。
- `rfauto ads-circuit run` — J3+J4 一条龙：读图→合参→渲染→hpeesofsim→解析→指标→对拍→反标注。
- `rfauto ads-circuit annotate` — 离线反标注：原图+circuit_result.json → 指标上图（不重跑仿真）。

## rfauto watchdog

seat 粒度三证判活（watchdog 方法论 CLI 出口；service/watchdog_service 薄壳）：watch=单席判活一次性视图（缺省动作）或 --watch 常驻循环（显式开启；jsonl 落白名单 runs/watchdog/，Ctrl+C 优雅停）

共 1 条叶子命令。

- `rfauto watchdog watch` — 单席三证判活：pid / census 指纹 / 纯产物三形态 → alive·stalled·dead·

## rfauto cal-wizard

校准件设计向导（TRL 设计单+覆盖核算+测试连接图；service/cal_wizard_service 薄壳）：trl=频带+介质→Thru/Reflect/Line 设计单（Line λg/4、8:1 覆盖核算、多 Line 分带）

共 1 条叶子命令。

- `rfauto cal-wizard trl` — TRL 校准件设计单（频带+介质 → Thru/Reflect/Line 几何+覆盖核算）。

## rfauto liberty

Liberty (.lib) 时序库结构化解析（cells/pins/timing 查找表/功率）

共 2 条叶子命令。

- `rfauto liberty parse` — 结构化解析 Liberty 库（NLDM 查找表/功率/工况/模板，缺省紧凑面）。
- `rfauto liberty list` — 库清单（cell 名/面积/pin 数/表数+模板与工况名录，只读零写盘）。

## rfauto spice

SPICE 网表深度解析（ngspice/HSPICE/Spectre 三格式统一结构化；service/spice_netlist_service 薄壳）：parse=五维度解析（元件/子电路/控制语句/模型卡/拓扑）

共 1 条叶子命令。

- `rfauto spice parse` — SPICE 网表深度解析（三格式统一五维度结构化输出+拓扑摘要）。

## rfauto skill

SKILL 代码模板生成（Python→.il 脚手架；零 Virtuoso 依赖，执行侧在用户本地 Virtuoso）

共 3 条叶子命令。

- `rfauto skill list` — SKILL 模板目录（注册表只读视图：名称/分类/变量面/函数面）。
- `rfauto skill render` — 渲染 SKILL 代码（模板+变量直出，零手拍电路数值；含语法守卫）。
- `rfauto skill lint` — SKILL 语法守卫（括号/引号/let 绑定/函数名白名单/赋值目标）；有

## rfauto sdc

SDC（Synopsys Design Constraints）约束结构化解析（时钟/IO 延迟/路径例外/负载驱动，Tcl 语法子集只读面）

共 2 条叶子命令。

- `rfauto sdc parse` — 结构化解析 SDC 约束（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto sdc list` — SDC 清单（命令名录+计数、时钟名录、对象 pattern 计数，只读）。

## rfauto exploded-view

版图 3D 爆炸视图（layered_stack/KiCad→SVG/JSON/PNG+lint 闭环）

共 1 条叶子命令。

- `rfauto exploded-view render` — 渲染 3D 爆炸视图（lint 零 ERROR 才渲染；确定性 sha256 落档）。

## rfauto layer-3d

KiCad .kicad_pcb 逐层 3D 渲染导出（铜/阻焊/丝印/钻孔逐层 PNG+叠层合成预览 PNG/SVG；service/layer_3d_render_service 薄壳）

共 1 条叶子命令。

- `rfauto layer-3d render` — KiCad 板逐层 3D 渲染导出（逐层 PNG+合成预览；零 pcbnew 零 license）。

## rfauto drc

DRC 规则文件结构化解析（JSON/CSV/自由文本统一 schema+RF 特化检查：阻抗精度/焊盘间距/地过孔围栏/屏蔽罩间距，只读面）

共 2 条叶子命令。

- `rfauto drc parse` — 结构化解析 DRC 规则文件（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto drc validate` — design × 规则集校验（verdict=issues/attention/clean；违规≠exit 1）。

## rfauto lvs

LVS 网表对照（Layout vs Schematic，netgen 思想借鉴化用；service/lvs_compare_service 薄壳）：compare=两份网表拓扑一致性（图同构+missing/extra/mismatched+RF 特化）

共 1 条叶子命令。

- `rfauto lvs compare` — LVS 网表对照（图同构+元件/参数/端口差异清单+对照报告）。

## rfauto ibis

IBIS (.ibs) IO buffer 模型结构化解析（IV 查找表/暂态表/引脚）

共 2 条叶子命令。

- `rfauto ibis parse` — 结构化解析 IBIS 模型（缺省紧凑面：表计数在、表体不在）。
- `rfauto ibis list` — 清单（component/model 名录+表计数+选择器名录，只读零写盘）。

## rfauto verilog

Verilog 网表结构化解析（数字后端网表只读面：module/port/wire/assign/实例/参数+拓扑三件套）

共 2 条叶子命令。

- `rfauto verilog parse` — 结构化解析 Verilog 网表（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto verilog list` — Verilog 清单（模块名录+逐模块计数、顶层候选、实例化边，只读）。

## rfauto citi

CITIfile（HP/Keysight 仪器数据格式）读取：结构化解析+skrf 桥接探针

共 3 条叶子命令。

- `rfauto citi info` — 包级结构化信息（header/版本/变量/段概览；--max-values 截断值列）。
- `rfauto citi segments` — 数据段解码值读取（complex 值 JSON 形态=re、im 成对）。
- `rfauto citi network` — skrf 桥接探针（条件匹配才桥；不满足走 skipped 信封如实给原因）。

## rfauto sdf

SDF（IEEE 1497 标准延迟格式）时序标注解析：头部/CELL 段/IOPATH·INTERCONNECT·PORT 延迟+TIMINGCHECK 只读面

共 2 条叶子命令。

- `rfauto sdf parse` — 结构化解析 SDF 文件（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto sdf report` — 报告：头部+逐 celltype 计数+TIMINGCHECK 十二类计数与最坏值（只读）。

## rfauto gdsii

GDSII 版图交换格式结构化解析（二进制记录流只读面：边界/路径/引用/文本六桶+层级统计+层汇总）

共 2 条叶子命令。

- `rfauto gdsii parse` — 结构化解析 GDSII 文件（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto gdsii layers` — 层汇总（逐 (layer,datatype) 元素计数+包围盒，只读）。

## rfauto touchstone

Touchstone（.sNp）结构化解析：格式嗅探/rank 三规则推断/RI·MA·DB 解码只读面

共 1 条叶子命令。

- `rfauto touchstone info` — 格式嗅探+rank 三规则结果+冲突报告（缺省紧凑；--json 恒全结构信封）。

## rfauto ipc356

IPC-D-356/356A 裸板电气测试网表解析：头部/记录/net 测试点拓扑+统计+Gerber/Excellon 配对只读面

共 1 条叶子命令。

- `rfauto ipc356 report` — 报告：统计+单点 net 开路嫌疑清单；配对旗标切换 356×Gerber/Excellon

## rfauto lefdef

LEF/DEF 物理设计交换格式结构化解析（科技库 LEF 层/via/macro/引脚几何+版图 DEF 组件/引脚/网/走线+交叉校验三件套，只读面）

共 2 条叶子命令。

- `rfauto lefdef parse` — 结构化解析 LEF/DEF（--lef/--def 可单给可组合；缺省紧凑汇总，--json 恒全结构信封）。
- `rfauto lefdef check` — LEF×DEF 交叉校验（单元闭合/网连接度/引脚名对齐；verdict=clean/attention/issues，违规不改退出码）。

## rfauto stil

STIL 测试向量解析（IEEE 1450 只读面：Signals/SignalGroups/Timing/Pattern 结构化提取+向量与时序事件联查+覆盖统计）

共 2 条叶子命令。

- `rfauto stil parse` — 结构化解析 STIL（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto stil report` — STIL 统计与 timing/pattern 清单报告（逐 WFT 周期+逐 pattern 账目）。

## rfauto skill_parse

SKILL/OCEAN 源码 S-expression 解析（只读静态面：define/defun 盘点/API 前缀桶/全局赋值/静态调用图；零执行零 Virtuoso 依赖）

共 2 条叶子命令。

- `rfauto skill_parse parse` — 结构化解析 SKILL/OCEAN 文件（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto skill_parse report` — 报告：define/defun 盘点+API 前缀四桶+全局赋值面（只读静态分析）。

## rfauto odbpp

ODB++ 目录结构与制造库存解析：matrix 层清单/step 特征统计/cadnet 网表/net 库存（悬空 pad+空 net）/层叠对齐校验

共 1 条叶子命令。

- `rfauto odbpp report` — 报告：matrix 层清单+逐 step 统计+stack 对齐+悬空 pad/空 net 双清单。

## rfauto bsdl

BSDL 边界扫描描述解析（IEEE 1149.1 只读面：entity/port/TAP/引脚映射/指令表/边界寄存器单元+控制链校验+长度一致性三数字）

共 2 条叶子命令。

- `rfauto bsdl parse` — 结构化解析 BSDL（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto bsdl report` — BSDL 统计与指令/边界一致性报告（指令表+function 分桶+长度三数字）。

## rfauto spectre

Spectre 网表解析（Cadence 模拟仿真器原生语法只读面：parameters/subckt 层次/器件库存/选项块登记，表达式只保留原文不求值）

共 2 条叶子命令。

- `rfauto spectre parse` — 全结构化解析（parameters 声明表/subckt 层次表/顶层实例/选项块+引用登记）。
- `rfauto spectre report` — 统计聚合（器件库存+参数键频次 top+层次摘要+参数引用点计数）。

## rfauto veriloga

Verilog-A 模拟行为级结构子集解析（只读面：模块/端口/net/参数/analog 行为块+贡献语句表+表达式前缀归一）

共 2 条叶子命令。

- `rfauto veriloga parse` — 结构化解析 Verilog-A（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto veriloga report` — Verilog-A 统计报告（逐模块摘要+全模块参数表+贡献对清单）。

## rfauto stdf

STDF 产线测试数据解析（Teradyne V4 只读面：FAR 字节序自描述/MIR 摘要/PIR-PRR 器件/PTR-FTR 测试两记录面/良率两口径+查询）

共 2 条叶子命令。

- `rfauto stdf parse` — 结构化解析 STDF（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto stdf report` — STDF 盘点报告（良率两口径+fail parts+记录计数+截断态）。

## rfauto ibis-ami

IBIS-AMI (.ami) 参数文件解析（IBIS 7.0 只读面：Reserved 保留参数字典+必备键缺失清单、Model_Specific 五键逐参+type 分派+in-bounds 开闭区间结构化、DLL/SoC 引用登记）

共 2 条叶子命令。

- `rfauto ibis-ami parse` — 结构化解析 AMI 参数文件（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto ibis-ami report` — AMI 统计报告（逐保留参数行+逐参数行+DLL/SoC 引用+缺失清单）。

## rfauto spef

SPEF 寄生交换格式解析（IEEE 1481 寄生网络只读面：头部/NAME_MAP/PORTS/D_NET 四段+拓扑与耦合统计）

共 2 条叶子命令。

- `rfauto spef parse` — 结构化解析 SPEF（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto spef report` — SPEF 拓扑与耦合统计报告（逐 net 连通分量/孤立节点+耦合 top-k）。

## rfauto vcd

VCD 波形解析（IEEE 1364 Value Change Dump 只读面：声明段/scope 层次/信号事件流+活跃度与时间窗统计）

共 2 条叶子命令。

- `rfauto vcd parse` — 结构化解析 VCD（缺省紧凑汇总；--json 恒全结构信封）。
- `rfauto vcd report` — VCD 时间跨窗与信号活跃度报告（时间窗直方+top 活跃度聚合）。

## rfauto tri-view

原理图↔版图↔3D 三视图联动（位号 ref 为键 1:1 映射+交叉高亮+联动 SVG 三联）

共 1 条叶子命令。

- `rfauto tri-view link` — 三视图联动：位号键 1:1 映射+交叉高亮数据+联动 SVG 三联（同输入逐字节同）。

## rfauto aedt-migrate

老版本 .aedt 工程批量迁移：五阶段决策树+迁移报告（help 明细见各叶）

共 3 条叶子命令。

- `rfauto aedt-migrate run` — 批量迁移编排：收集→S0 盘点→逐工程决策树→报告落 reports。
- `rfauto aedt-migrate status` — 迁移报告结构化摘要（verdict/阶段链/体检/对比/引擎指纹）。
- `rfauto aedt-migrate report` — 迁移报告人读全文（分节 rich 面；--json=报告原文逐键透传）。
