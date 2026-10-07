# 能力目录（CLI × MCP 入口映射）

> CLI 顶层 **110** 组 / **254** 条叶子命令，MCP 工具 **149** 个（分布在 38 个模块）。同名行=同域双入口（CLI 给人、MCP 给 agent）；“—”表示该域暂无同名另一侧入口。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改；CLI 树与 check_numbers 同源互证，条目明细见[CLI 参考](cli.md)与[MCP 参考](mcp.md)。

## 双入口域（CLI 组 ↔ MCP 同名模块）

| CLI 组 | 叶数 | MCP 同名模块 | CLI 组说明 |
|---|---|---|---|
| `afs` | 2 | — | AFS 自适应频扫（M-3：向量拟合驱动选频点，收敛即停；JSON 进出薄壳） |
| `agent` | 2 | `agent`（6 个） | Agent 提案/执行编排（E4b 三层 Gate） |
| `aging` | 3 | `aging`（3 个） | 器件老化漂移（F-C：PoF 时间轴→εr 漂移→EOL 失谐判据，fake 通道） |
| `anchors` | 5 | `anchors`（2 个） | 物理标定锚注册表（DP-3，JSON 进出薄壳） |
| `array` | 3 | — | 阵列/相控阵两档方向图引擎（DP-4：快速档单元×AF；互耦档 P3 接口预留） |
| `audit` | 1 | — | 查看 Agent 审计日志（audit.jsonl）。 |
| `autotune` | 1 | — | 确定性 critique 自治调优环（无人在环；数值只在确定性内核）。 |
| `bands` | 10 | `bands`（10 个） | 标准频段/环境包络注册表（D9，十接口；数值只出自 core/bands 常量表） |
| `bench` | 6 | — | AgentBench/goldset 回归门（WP3.7/F6）——离线、确定性、零网络 |
| `budget` | 1 | — | 链路预算（E8c） |
| `cache` | 1 | — | 缓存管理 |
| `calc` | 2 | — | 微波闭式计算器（E4：mm/GHz/Ω/dB 口径） |
| `campaign` | 5 | — | 战役状态机（calibrate→prefilter→tune→tolerance→report→final_verify） |
| `cascade` | 3 | — | 系统级级联预算+混频杂散搜索（DP-5） |
| `certify` | 1 | `certify`（4 个） | 公差盒 → 指标区间证书（三值门面：逐目标 PASS/FAIL/UNKNOWN + 总 verdict）。 |
| `chain` | 2 | — | 有源链路分析（C14：LNA 匹配链 / PA load-pull 口径） |
| `chat` | 1 | — | LLM 对话窗（方向 6j 双通道可选）：内嵌 service 直调 或 MCP 客户端。 |
| `compose` | 1 | — | 模板几何组合（DP-8）：netlist YAML → 单一 simulation.py（布局合并路线）。 |
| `compose-templates` | 1 | — | 列出已注册组合契约模板与 pin schema（DP-8 opt-in 台账）。 |
| `constraints` | 1 | — | 渲染前声明式几何约束检查（R4：z3 一次求解，UNSAT 冲突组+witness） |
| `correlate` | 1 | — | 仿真 vs 测量相关性分析。 |
| `cryo` | 1 | — | 低温材料面（F-H.4：铜面全量+可选超导节/Q 分解估计） |
| `dag` | 2 | — | DAG 执行基座（断点续跑/CAS/watchdog/#261 互斥；pipeline.dag_runner） |
| `datasets` | 8 | `datasets`（4 个） | 数据集注册表 v2（runs 点级数据 → Parquet + SQL 查询） |
| `datasheet` | 1 | — | 器件 datasheet 生成（EP-4：run 报告/模板名义 → 规格书 md/HTML） |
| `db` | 8 | `db`（6 个） | 注册表数据库（SQLite 事务型注册表 + DuckDB 分析直读；零服务器） |
| `design` | 2 | — | level2 设计链（NL 意图→族路由→综合→kickoff 草稿→闭环） |
| `dev` | 2 | — | 维护者脚手架（骨架生成+消费钉清单，SO §7 P5） |
| `diagnose` | 5 | `diagnose`（4 个） | 耦合矩阵/Q 诊断三件套（DP-2，JSON 进出薄壳） |
| `doctor` | 1 | — | 环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。 |
| `electrothermal` | 1 | — | Wilkinson 隔离电阻损耗 → 温升 → 材料温漂 → S 参数失谐（+带内判据），纯闭式。 |
| `even-odd` | 1 | — | 奇偶模分解报告（对称性检查+半模型切割+端口改写表+守卫，只读）。 |
| `explain-run` | 1 | — | 失败指纹解释（DP-17 W2：确定性指纹匹配→候选根因族+取证命令+坑号链，无 LLM）。 |
| `export-report-pdf` | 1 | — | 把已完成 run 的指标导出为多页 PDF 报告（WP4.7）。 |
| `fab` | 9 | — | HFSS → 可机加交付包（STEP/x_t + DXF 图 + 审计门禁，T43） |
| `farfield` | 2 | — | 远场方向图/增益/效率/SAR（WP4.1 nf2ff 产物视图） |
| `fault-tree` | 1 | — | 故障树分析（QM-FTA：playbook→OR-of-AND 树+最小割集+Mermaid 图） |
| `few-shot` | 1 | — | 成功会话 few-shot 精选（AD-3：挖掘→精选→注入节） |
| `firmware` | 3 | — | 固件工件三出口（波束码字/变容管 DAC/DPD 定点，§B-6） |
| `goal` | 4 | — | 持久目标（用户 Goal 工作模式：跨重启存续+自动续轮，DS-3） |
| `hfss-import` | 1 | — | HFSS 工程导入器：读变量/扫参范围/Setup-Sweep/端口 → 设计规格 + 配方草稿。 |
| `hints` | 1 | — | 错误提示规则面（错误指纹 → 可行动提示，只读） |
| `humidity` | 2 | — | 湿度吸湿漂移（F-H.2：Fick 吸湿估计+MSL 车间寿命查询） |
| `inbox` | 1 | — | 审批收件箱：查看/批准待确认的 Agent 提案（方向 6i）。 |
| `interop` | 2 | — | Touchstone 互操作（ME-10'：TS 2.1 写出 + HFSS 注释块直读） |
| `jobs` | 3 | `jobs`（6 个） | 任务管理 |
| `kicad` | 6 | — | KiCad 板级链路（E7a：P-Cell 生成 + DRC gate） |
| `lake` | 10 | — | runs/ 湖索引与分层压实（df7 F3：DuckDB 索引 + tar.zst 内容寻址归档） |
| `layout` | 8 | — | 版图家族（生成与互操作、装配、diff、LVS、拼板、仿真组装、钢网、STEP） |
| `link` | 1 | — | 把某次 HFSS 结果送进 ADS 联动链路（P3, N=2 往返；--to-ads 才执行）。 |
| `lint` | 1 | — | 设计体检一次查：约束/bounds/DFM/PDN/stub 聚合面（JSON 进出薄壳）。 |
| `logs` | 1 | — | 日志语义蒸馏（LogDistiller：stdout/审计 JSON→结构化 digest） |
| `materials` | 1 | — | 材料库工具（D1 色散适应性报告；只读） |
| `mmt` | 1 | `mmt`（2 个） | RWG/SIW 模基 MMT 求解（DP-1：段表 mm + 频网 → 50Ω S 参数，秒级零外部进程） |
| `models` | 2 | — | 模型管理 |
| `nfc` | 3 | — | NFC/WPC 平面螺旋线圈闭式（DP-18 C10b） |
| `nfmeas` | 2 | `nfmeas`（6 个） | 近场测量变换与 .ffs 视图（DP-18 C10a） |
| `p0` | 1 | — | 方向 1 P0 实验：多保真验证（fake 先行）。 |
| `parasitic` | 1 | — | PCB 互连 RLC 提取链：pcell 几何 → RF-DRC 门 → 闭式锚 →（Q3D 注入对比 ≤5％ 门）。 |
| `pcell` | 4 | — | PCell 参数化单元 DSL（LC-2 复活：库清单/定义/求值/渲染 Layout 出口） |
| `pdn` | 3 | `pdn`（3 个） | PI/PDN AC 阻抗域分析（F-B：目标阻抗/去耦选型/平面腔模门） |
| `port-gate` | 1 | — | 端口尺寸收敛前置门（合成回放 JSON 面；防 #191/#254 浪费求解席位）。 |
| `preflight` | 2 | `preflight`（1 个） | XC-F 开工前统一预检（极限/功率/热/加工/精度档案五门联合） |
| `profile` | 2 | — | 剖析入口（PR-8）：py-spy 火焰图落 runs/（py-spy 为可选依赖） |
| `rag` | 3 | — | RAG 知识库词法检索（BM25，只读、citation 可溯） |
| `rationale` | 3 | `rationale`（4 个） | 设计理由/经验记忆（F11 typed 经验检索 + F2 runs 理由语料 TF-IDF） |
| `recipe` | 3 | — | 配方版本管理（方向 7） |
| `refine` | 1 | — | 热启动续调：以上轮 best 为起点，继续优化。 |
| `remote` | 2 | `remote`（2 个） | 多机协同仿真资源（探活/状态；v0：HFSS gRPC 远程会话+SSH 通道） |
| `replay` | 1 | — | 复现：用该 run 的 recipe 快照重跑，并核对 plugin/schema 版本。 |
| `report` | 1 | — | 按已完成的 run 重建报告（markdown / html）。 |
| `report-narrative` | 1 | — | F9 叙述位：run 白名单 → 确定性模板叙述，或审计外来叙述（未授权数字定位；不调 LLM）。 |
| `reports` | 1 | — | 双输出报告链（DP-13 U1：run → 同一报告模型双出 PDF+HTML） |
| `repro` | 1 | — | 导出可复现包（配方快照 + 求解器输入 + S 参数 + reproduce.py）。 |
| `repro-manifest` | 1 | — | 组装复现清单（环境段+可选产物段）并落盘（reproducibility_service）。 |
| `repro-verify` | 1 | — | 校验复现清单（产物三态差异+环境 packages/lock 差异，如实报告）。 |
| `run` | 1 | — | 单次仿真（build → solve → post → 导出）。 |
| `runs` | 8 | `runs`（7 个） | run 历史对比 |
| `sandbox` | 3 | — | agent 配方沙箱治理（草稿列表/差异/三层 Gate 提案） |
| `sar` | 1 | — | SAR 合规后处理（DP-18 C10c） |
| `self-heal` | 1 | — | 自愈环只读诊断（F5：日志面→确定性 critique→根因/建议） |
| `sensitivity` | 1 | — | 灵敏度分析：Sobol/Morris 参数重要度排序（方向 8b）。 |
| `si` | 2 | — | SI 通道报告（df7 T2：无源性/因果性/TDR/COM，纯后处理） |
| `simci` | 1 | — | 全配方夜间回归：validate+run → 对照 runs 索引历史基线 → diff 报告。 |
| `simci-pin-baseline` | 1 | — | sim_ci golden 基线三动作：pin 钉定 / compare 对照 / drift 漂移量化。 |
| `slotline` | 2 | `slotline`（5 个） | 槽线闭式（Janaswamy–Schaubert 1986：分析/综合；越有效域拒绝不外推） |
| `solid-import` | 1 | — | STL 实体导入：解析+分类+CSX 载荷（B3；一切失败 ok=False 不抛出）。 |
| `solvers` | 4 | — | 求解器管理（方向 6g/6h） |
| `sparams-compare` | 1 | — | run 与外部 .sNp 的 S 参数叠画对比（dB，WP0.3/E8）。 |
| `stats` | 3 | — | 量产统计三件套（保护带/能力指数/Weibull 寿命，§B-5） |
| `study` | 1 | — | 人机参数注入研究（方向 6a/4d） |
| `surrogate` | 2 | — | 代理模型离线分析（E3） |
| `sweep` | 1 | — | 参数扫描（先粗扫缩小范围再交给精调）。 |
| `syn` | 5 | — | 微带线综合（E6a） |
| `teaching` | 2 | — | 模板教学卡（物理推导+敏感性排序+教科书索引） |
| `template-spec` | 3 | — | 模板库 TemplateSpec 注册表（E2：清单 + 综合草稿） |
| `tolerance` | 1 | — | 公差/良率分析（Monte Carlo，规格取自 objectives）。 |
| `tolerance-allocate` | 1 | — | cost-aware 公差分配（敏感度×成本系数 → 逐参数公差建议 + 对照法 + Cpk）。 |
| `topology` | 1 | — | 滤波器拓扑提议（typed，禁数值字段）→ 综合初值 →（--campaign）小战役精算。 |
| `transitions` | 3 | — | MSL↔槽线过渡与 Marchand 巴伦设计（微带 HJ 综合 + 槽线闭式精算） |
| `tune` | 1 | — | 启动优化外环（TPE / NSGA-II / --fidelity auto 多保真）。 |
| `tuning-report` | 1 | — | 生成增强调优报告（方向 8c）：指标摘要 + 诊断 + 可复现信息。 |
| `ui` | 1 | — | 启动人工核验 UI（浏览器查看/修改配方、3D 模型、S 参数与中间产物）。 |
| `uq` | 4 | `uq`（5 个） | 公差/良率收口（WP4.2：名义点良率 / 设计中心化 / D9 温区良率） |
| `validate` | 1 | — | 校验配方文件（不执行仿真）。 |
| `vna` | 4 | `vna`（3 个） | VNA 测量闭环（DP-11：En 相关性报告 + 离线回放） |
| `vna-replay` | 1 | — | mock 仪表采集→校准→相关全链回放（零硬件；硬件阻塞下的回归入口）。 |
| `warm-start` | 1 | — | 数据集历史样本 → warm-start 先验注入优化（相似度门在 warm_start 内）。 |
| `weave` | 2 | — | 玻纤编织 skew（HS-1：样式表查询+最坏/期望 skew 估计） |
| `zenodo` | 2 | — | Zenodo 元数据导出与 CITATION.cff 校验（PR-11，零网络） |

双入口域共 **19** 个。计算器键与器件模板另见[计算器注册表](calculators.md)与[模板库](../catalog/index.md)（数字构建时实测互证）。

## 仅 MCP 侧模块（无同名 CLI 组）

| 模块 | 工具数 |
|---|---|
| `adc` | 2 |
| `afs_interop` | 2 |
| `agent2` | 3 |
| `basic` | 3 |
| `datasets_ops` | 4 |
| `emc` | 4 |
| `env_reliability` | 8 |
| `explain` | 3 |
| `farfield_kicad` | 4 |
| `guidelines` | 1 |
| `knowledge` | 1 |
| `metasurface` | 2 |
| `multiphysics` | 3 |
| `ops` | 3 |
| `optim` | 2 |
| `report_bench` | 4 |
| `si_lake` | 4 |
| `specs_campaign` | 7 |
| `synth` | 6 |

共 **19** 个模块（facade 直定义工具也在此列，如实分标）。
