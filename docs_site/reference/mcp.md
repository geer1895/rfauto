# MCP 工具参考

> `@mcp.tool` 注册工具共 **149** 个（ast 枚举与 `scripts/check_numbers.py` 的 `count_mcp()` 装饰器正则计数构建时逐位互证）。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改；逐工具可调用性双检见 `tests/unit/test_mcp_tool_consistency.py`。

| 工具 | 模块 | 说明 |
|---|---|---|
| `adc_interleave_spurs` | adc | ADC 交错杂散表（adc 域）：fs/fin/路数 → 失配杂散清单（折叠第一奈区）。 |
| `jitter_budget_snr` | adc | 抖动预算 SNR（adc 域）：RJ/DJ/BER → TJ 与等效 SNR（UI 域闭式）。 |
| `afs_plan` | afs_interop | AFS 频扫计划（afs 域）：频带 → 初始频点表+加密协议+验收判据。 |
| `read_hfss_touchstone_comments` | afs_interop | HFSS Touchstone 注释直读（afs 域）：.sNp 路径 → Gamma/Zpi 注释块。 |
| `rf_propose_params` | agent | 调优提议内核（agent 域）：bounds/fixes → 初值落参+探测候选展开。 |
| `rf_run_sampler` | agent | 验证采样内核（agent 域）：params → metrics/valley（唯一产数环节）。 |
| `rf_critique_point` | agent | 评审内核（agent 域）：metrics+objectives → verdict/issues/typed fixes。 |
| `rf_spec_cost` | agent | SpecEvaluator cost 内核（agent 域）：metrics+objectives → 加权 cost。 |
| `multi_agent_run` | agent | 评审/调优/验证三角色端到端（LangGraph 式图 + MCP 工具层 + A2A，WP3.8）。 |
| `autotune_self_verify` | agent | 自验证环（agent 域）：propose→verify→fix 闭环+里程碑分解+执行看板。 |
| `even_odd_report` | agent2 | 奇偶模分解报告（agent2 域）：模板+参数 → 对称性检查+半模型切割表。 |
| `mcts_search` | agent2 | MCTS 设计搜索（agent2 域）：样本集最优点 → 定向序列探索最优候选。 |
| `inverse_prefilter` | agent2 | 逆设计前滤波（agent2 域）：目标指标 → k 个候选参数起点（fake 语料）。 |
| `aging_simulate` | aging | 老化漂移仿真（aging 域）：任务剖面→εr 漂移轨迹→名义/EOL 两点 S 参数+失谐量。 |
| `aging_verdict` | aging | EOL 失谐判据（aging 域）：\|detune_pct\| ≤ spec → PASS/FAIL（确定性）。 |
| `aging_report` | aging | 老化报告（F-C P2）：mission_profile 表/漂移轨迹/EOL 判据/法源 provenance 四节。 |
| `anchors_list` | anchors | 列出物理标定锚注册表全部锚（DP-3，knowledge/anchors.yaml）。 |
| `anchors_inspect` | anchors | 单锚全量记录查询（anchors 域）：锚 id → provenance/不确定度/消费面。 |
| `bands_list` | bands | 频段清单查询（bands 域）：过滤词 → 标准频段注册表条目清单。 |
| `bands_get` | bands | 按 key 取单条频段详情（边界/出处/区域）。 |
| `bands_find` | bands | 频段查询（bands 域）：频率 GHz → 覆盖该频率的全部频段条目。 |
| `bands_spec_bounds` | bands | 频段 band 结构查询（bands 域）：频段键 → SpecEvaluator band 界。 |
| `bands_env_list` | bands | 环境包络清单查询（bands 域）：过滤词 → 包络注册表条目清单。 |
| `bands_env_get` | bands | 按 key 取单条环境包络详情（温区/等级/出处）。 |
| `bands_env_find` | bands | 环境包络查询（bands 域）：温度 °C → 覆盖该温区的全部环境包络。 |
| `bands_env_delta_t` | bands | 环境包络 ΔT 界查询（bands 域）：包络键 → ΔT 上下限（°C）。 |
| `bands_env_uq_axis` | bands | UQ 温度轴查询（bands 域）：包络键 → 名义点+σ+ΔT 上下限（°C）。 |
| `bands_env_points` | bands | 环境包络采样（bands 域）：包络键 → 温区等距采样点（含两端）。 |
| `doctor` | basic | 环境探测（basic 域）：AEDT/ADS 版本/license/路径/版本组合逐项体检。 |
| `list_models` | basic | 列出已注册的模型插件。 |
| `validate_recipe` | basic | 校验配方文件（recipe 域）：YAML 路径 → 结构校验结论，不执行仿真。 |
| `render_constraint_check` | certify | 渲染前约束求解（certify 域）：声明式 config → UNSAT 冲突组+witness。 |
| `import_solid_payload` | certify | STL 实体导入（certify 域）：STL 路径 → 解析+分类+CSX 载荷。 |
| `certify_design` | certify | 公差盒 → 指标区间证书（三值门面：逐目标 PASS/FAIL/UNKNOWN + 总 verdict）。 |
| `port_gate` | certify | 端口尺寸收敛前置门（DP-16 C4；JSON 进出合成回放面）。 |
| `list_datasets` | datasets | 数据集清单查询（datasets 域）：过滤词 → 注册表总览（点数/GT/可见性）。 |
| `query_dataset` | datasets | 数据集 DuckDB 直查（datasets 域）：SQL WHERE/列裁剪 → 行集（只读）。 |
| `discover_workdir_runs` | datasets | 工作目录产物发现（datasets 域）：runs 扫描 → 可导入候选清单（只读）。 |
| `import_workdir_runs` | datasets | 工作目录产物导入（datasets 域）：候选目录 → 数据集注册表行集。 |
| `dataset_coverage` | datasets_ops | 数据集覆盖度报告（datasets_ops 域）：数据集名 → 逐维占用/最弱维。 |
| `dataset_annotate_ground_truth` | datasets_ops | ground truth 标注（datasets_ops 域）：白名单源清点 → manifest 回写。 |
| `dataset_set_visibility` | datasets_ops | 数据集可见性切换（datasets_ops 域）：public/private → manifest 回写。 |
| `dataset_export_hf` | datasets_ops | HF 数据集导出（datasets_ops 域）：数据集 → parquet 分片+数据卡目录。 |
| `db_init` | db | 注册表建库（db 域）：db_path → SQLite 建库+幂等迁移（applied 计数）。 |
| `db_migrate` | db | 注册表幂等迁移（db 域）：schema_version 递增（重复执行零变更）。 |
| `db_status` | db | 注册表状态盘点（db 域）：db_path → 存在性/schema 版本/各表行数。 |
| `db_reindex_runs` | db | runs 重索引（db 域）：扫 runs/*/meta.json → runs 表 upsert 重建。 |
| `db_query` | db | 只读查询注册表：仅单条 SELECT + ? 占位符参数绑定（白名单纵深防御）。 |
| `db_analytics_attach` | db | DuckDB sqlite 扩展直读注册表文件（零拷贝分析面）：逐表计数 + 最近 runs 示例。 |
| `cm_diagnose_q` | diagnose | 单腔 Q 诊断（cm 域）：S11 → VF 极点 × Kajfez 圆拟合互证+skrf 仲裁。 |
| `cm_extract_refine` | diagnose | 耦合矩阵提取（cm 域）：S 参数 → VF 定阶+LM 拓扑精化（+目标偏差表）。 |
| `cm_cat_critique` | diagnose | Dishal 调谐 critique（cm 域）：τ(f) 峰数指纹+Qe/k 偏差 → typed fixes。 |
| `correlate_measurement` | diagnose | 仿真 vs 测量相关性分析（measurement 域）：两份 .s2p → 相关性判定。 |
| `emc_cispr_band_params` | emc | CISPR 检波器参数表（emc 域）：Band A/B/C/D → 16-1-1 Table 1 四参数。 |
| `emc_cispr_detect` | emc | CISPR 三检波器读数（emc 域）：时域波形 → Peak/QP/Avg dBµV。 |
| `emc_ground_spacing_check` | emc | 接地间距判据（emc 域）：间距/频率 → λ/20 等电位判据（Ott/Paul）。 |
| `emc_cm_radiated_budget` | emc | CM 辐射预算（emc 域）：浮地-机壳耦合电容 → I_CM → Ott 辐射场。 |
| `fault_tree_report` | env_reliability | 故障树报告（QM-FTA 复合工具）：playbook→OR-of-AND 树+孤儿审计+最小割集；out_format 为 mermaid 时附图文本。 |
| `build_datasheet` | env_reliability | 器件规格书生成（EP-4 复合工具）：run 报告模型（PR-4）+模板名义 → rfauto-datasheet/v1 模型+md/HTML 渲染全文。 |
| `netlist_goldset_replay` | env_reliability | 网表 goldset 回放门（AI-6）：构造 qucsatorRF 真通道逐任务回放，对照 gold 值按容差打分出 PASS 率门。 |
| `humidity_uptake` | env_reliability | 湿度吸湿估计（env_rel 域）：时长/扩散系数/板厚 → Fick 级数+√t 律。 |
| `msl_floor_life_query` | env_reliability | MSL 车间寿命查询（env_rel 域）：msl 等级 → J-STD-033 floor life（h）。 |
| `weave_style_info` | env_reliability | 编织样式表查询（env_rel 域）：样式键 → 织构参数+MIT 出处（只读面）。 |
| `weave_skew_estimate` | env_reliability | 编织 skew 估计（env_rel 域）：样式/方向/走线长/树脂 εr → skew+UI 判定。 |
| `cryo_surface_estimate` | env_reliability | 低温材料面估计（env_rel 域）：温度/RRR/频率 → 铜面 ρ/Rs/δ/l/f_c 全量。 |
| `explain_run` | explain | 失败指纹解释（explain 域）：run 目录 → 确定性指纹匹配候选根因族。 |
| `list_composable_templates` | explain | 列出已注册组合契约模板与 pin schema（DP-8 opt-in 台账）。 |
| `error_hints_lookup` | explain | 错误提示检索（explain 域）：错误消息文本 → 可行动 hint 表（零 LLM）。 |
| `farfield_runs` | farfield_kicad | 远场 run 清单（farfield 域）：扫描 → 含 nf2ff/SAR 产物 run 候选表。 |
| `farfield_view` | farfield_kicad | 远场视图（farfield 域）：run id → φ 切面 θ-dB 序列+Dmax/效率/SAR。 |
| `kicad_extract` | farfield_kicad | PCB 事实提取（kicad 域）：.kicad_pcb → 叠层/走线/过孔/板框/zone 表。 |
| `kicad_optimize_cpw` | farfield_kicad | CPWG 寻优环（kicad 域）：PCB 提取 → 闭式代理调宽（\|z0−target\|≤tol）。 |
| `get_guidelines_for` | guidelines | 坑规指南检索（guidelines 域）：主题词 → 坑账/playbook/规则三源命中。 |
| `create_run` | jobs | 提交仿真任务（jobs 域）：配方+适配器 → 同步求解并返回 run_id。 |
| `create_run_async` | jobs | 异步提交仿真任务（jobs 域）：配方+适配器 → 立即返回 job_id。 |
| `poll_job` | jobs | 任务状态轮询（jobs 域）：job_id → state/进度/指标快照（只读）。 |
| `cancel_job` | jobs | 协作取消长任务（jobs 域）：job_id → 置 cancelled 协作检查点退出。 |
| `wait_job` | jobs | 阻塞等待长任务终态并流式回报进度（DP-14 A1：progressToken 语义）。 |
| `get_metrics` | jobs | 读取 run 指标（runs 域）：run_id → 指标/成本/诊断信封。 |
| `search_knowledge` | knowledge | 知识库统一检索（QW-2）：rules/anchors/playbook/fab 剖面一键子串检索。 |
| `metasurface_coding_pattern` | metasurface | 编码超表面方向图（metasurface 域）：码矩阵 → 远场摘要（2D DFT 权面）。 |
| `metasurface_quant_loss_db` | metasurface | 量化损失双报（metasurface 域）：bits/阵规模 → 理论 sinc²+实测峰比（dB）。 |
| `mmt_solve` | mmt | MMT 段表求解（mmt 域）：RWG/SIW 段表 → GSM 级联 S 参数（秒级）。 |
| `compose_netlist` | mmt | 模板几何组合（mmt 域）：rfauto-netlist-v1 三段式 → simulation.py。 |
| `electrothermal_chain` | multiphysics | 电-热-漂移链（multiphysics 域）：Wilkinson 损耗 → 温升 → S 失谐。 |
| `parasitic_extract_rlc` | multiphysics | 寄生 RLC 提取链（multiphysics 域）：pcell 几何 → DRC 门 → 闭式锚。 |
| `topology_propose` | multiphysics | 滤波器拓扑提议（multiphysics 域）：FilterSpec → typed 提议+初值。 |
| `nfmeas_ffs_info` | nfmeas | 审计 HFSS .ffs 远场文件头（nfmeas 域）：路径 → 频率/三功率/轴序。 |
| `nfmeas_cut_view` | nfmeas | .ffs 切面视图（nfmeas 域）：单频块 → 固定 φ 取 θ 扫描（或反之）。 |
| `nfc_coil_evaluate` | nfmeas | NFC 平面螺旋电感评估（nfc 域）：几何 → Mohan 1999 电感闭式（H）。 |
| `nfc_coil_synthesize` | nfmeas | NFC 线圈综合（nfc 域）：目标电感 → 外径二分反解（回代自洽 ≤1e-10）。 |
| `nfc_coil_q` | nfmeas | NFC 线圈 Q 评估（nfc 域）：频率+线圈参数 → 有载/无载 Q（T 模型精确式）。 |
| `sar_analytic_plane_wave` | nfmeas | 平面波 SAR 闭式对照（sar 域）：组织参数+深度 → 随深衰减谱（判据锚）。 |
| `self_heal_run` | ops | run 只读自愈环（ops 域）：日志面蒸馏 → 确定性 critique → 根因+建议。 |
| `log_digest` | ops | 日志文件 / 审计 JSON / run 目录 → 结构化 digest（WP3.6 LogDistiller）。 |
| `dispersion_report` | ops | 材料色散报告（ops 域）：Djordjevic-Sarkar 带内 εr/tanδ 漂移判据。 |
| `start_tune` | optim | 提交主优化任务（异步），立即返回 job_id。 |
| `run_sweep` | optim | 运行参数扫描（粗扫→精调，同步返回全量信封）。 |
| `pdn_analyze` | pdn | PDN 阻抗谱分析（pdn 域）：decap+VRM → 并联合成谱+反谐振峰+腔模。 |
| `pdn_select` | pdn | 贪心 decap 选型（pdn 域）：candidates+budget+target → 选中明细。 |
| `pdn_gate` | pdn | KiCad AC-PI 门（F-B P2）：平面腔模筛查+安装避让+可选 Z 谱裕量，三值 verdict。 |
| `preflight_run` | preflight | XC-F 开工前统一预检（精度档案/极限/功率/热/加工五门联合）。 |
| `rationale_recall` | rationale | F11 经验记忆检索：任务描述 → 命中历史坑/核对表/动作（确定性，无 embedding）。 |
| `rationale_checklist` | rationale | F11 冒烟前核对表门禁：模板名 → 核对表 + gate（命中即要求先离线审计）。 |
| `rag_query` | rationale | RAG 知识库检索（只读；citation 文件+标题+行号可溯）。 |
| `rag_explain` | rationale | RAG 检索 + 逐词 BM25 分数明细（tf/df/idf/contribution，打分可溯）。 |
| `remote_probe_machine` | remote | 机器 TCP 探活（remote 域）：登记机器 → 端口连通性+时延表。 |
| `remote_machine_status` | remote | 机器状态探活（remote 域）：TCP 端口+SSH 认证可达性（多机协同 v0）。 |
| `warm_start_optimize` | report_bench | warm-start 优化（report_bench 域）：数据集历史样本 → 先验注入求解。 |
| `export_report_pdf` | report_bench | PDF 报告导出（report_bench 域）：run 指标 → 多页 PDF（WP4.7）。 |
| `goldset_regression` | report_bench | 金标回归门（report_bench 域）：轨迹 vs 金标集 → TSA/FCA 判定。 |
| `agentbench_regression` | report_bench | AgentBench 回归门（report_bench 域）：两轴打分+公开/私有双集防污染。 |
| `diagnose` | runs | run 规则诊断（runs 域）：run_id → 指标规则诊断（确定性零 LLM）。 |
| `compare_runs` | runs | 双 run 对比（runs 域）：A/B run id → 逐指标 B-A 增量+cost 对照。 |
| `run_monitor` | runs | run 体检（runs 域）：run 目录 → 四类时序判据 verdict（零 LLM）。 |
| `get_run_artifacts` | runs | run 产物清单（runs 域）：run_id → 文件清单+metrics+S 参数摘要。 |
| `get_model_3d` | runs | 配方 3D 几何 spec（runs 域）：配方路径 → 毫米 boxes 列表（核验面）。 |
| `list_calculators` | runs | 计算器名单（runs 域）：注册表 → 名字/说明/参数表（mm/GHz/Ω/dB）。 |
| `run_calculator` | runs | 执行微波闭式计算器（微带/CPW/带状线正反解、λ/4 变换、π/T 衰减器、 |
| `si_channel_report` | si_lake | SI 通道报告（si_lake 域）：Touchstone/run → 无源性/因果性/TDR/COM。 |
| `lake_query_runs` | si_lake | runs/ 湖索引只读查询（df7 F3）：等值过滤+日期段，参数化 ? 绑定。 |
| `lake_pack_campaign` | si_lake | 战役冷层打包（si_lake 域）：战役目录 → tar.zst+偏移清单（只读源）。 |
| `com_pam4_run` | si_lake | 单点 COM 运行（si_lake 域）：.s4p 通道 → COM/FOM（pychopmarg 权威）。 |
| `slotline_analysis` | slotline | 槽线（slotline）闭式分析：Janaswamy–Schaubert 1986 分段拟合 (w, h, εr, f) → |
| `slotline_synthesis` | slotline | 槽线（slotline）综合：目标 Z0 → 槽宽 w（窄槽段括号 brentq 反解 + 闭式回代自洽）。 |
| `msl_slot_transition_design` | slotline | Roberts/Knorr MSL↔槽线过渡设计参数：微带 skrf HJ 综合 + 槽线闭式精算。 |
| `marchand_balun_design` | slotline | Marchand 巴伦对照设计（slotline 域）：f0/叠层 → 过渡参数+槽距（最小族）。 |
| `marchand_two_section_synthesis` | slotline | 两节对称 Marchand 巴伦电路级综合：f0 匹配闭式 → (Z0e,Z0o) → KJ 几何反解 (w,s) |
| `list_template_specs` | specs_campaign | 模板 spec 清单（specs 域）：注册表 → 组件齐备性/meta/physics_roles。 |
| `draft_recipe_from_spec` | specs_campaign | 配方草稿综合（specs 域）：模板名+入口参数 → recipe_draft（零求解）。 |
| `recommend_templates` | specs_campaign | 模板推荐（specs 域）：f0/族/端口数/关键词 → filter+rank 推荐表。 |
| `plan_campaign` | specs_campaign | 战役计划编制（specs 域）：配方 → 阶段队列（依赖/预算/license 门）。 |
| `save_campaign_plan` | specs_campaign | 战役计划落盘（specs 域）：plan dict → <out_dir>/campaign.plan.json。 |
| `get_campaign_status` | specs_campaign | 战役状态读回（specs 域）：plan_path → verdict/各阶段 status/计数。 |
| `run_campaign` | specs_campaign | 战役闭环执行（specs 域）：已落盘计划 → 逐阶段执行（VI-2 基座）。 |
| `synthesize` | synth | 微带线综合（synth 域）：目标阻抗+叠层 → 线宽（HJ 闭式反解）。 |
| `synthesize_bpf` | synth | BPF 耦合矩阵综合（synth 域）：N/f0/fbw/rl → Cameron N+2 矩阵。 |
| `budget_analysis` | synth | 链路预算分析（link 域）：级联器件链 → Friis 级联增益/噪声系数表。 |
| `cascade_budget` | synth | 级联预算（synth 域）：级表 → 增益/Friis NF/IIP3/P1dB/SFDR/灵敏度。 |
| `spur_search` | synth | 混频杂散搜索（synth 域）：f_RF/f_LO → \|m·f_RF±n·f_LO\| 落带判定表。 |
| `if_plan_sweep` | synth | IF 频率规划扫掠（synth 域）：候选 IF 逐点杂散判定 → spurious-free 窗。 |
| `uq_yield_at` | uq | 名义点良率（uq 域）：代理 MC 抽样 → 良率点值（确定性 seed 复现）。 |
| `robustness_report` | uq | 稳健性报告（uq 域）：良率 MC+FORM Pf+worst-case 角点+逐规范 Cpk。 |
| `uq_design_center` | uq | 设计中心化（uq 域）：容差盒网格违约 cost → 坐标搜索名义点。 |
| `uq_temperature_zone` | uq | 温区良率（uq 域）：环境包络温度轴并入 MC+温区两端角点评估。 |
| `uq_rare_yield` | uq | 稀有失效概率（uq 域）：FORM u* 喂重要性采样+MC 交叉核对。 |
| `vna_offline_replay` | vna | VNA 离线回放（vna 域）：历史 Touchstone → 采集→校准→相关全链。 |
| `vna_en_report` | vna | En 计量学相关性报告（vna 域）：实测 vs 参考 → \|En\|≤1 判定（DP-11）。 |
| `report_narrative` | vna | 报告叙述（vna 域）：run 白名单 → 确定性模板叙述/外来叙述审计。 |
