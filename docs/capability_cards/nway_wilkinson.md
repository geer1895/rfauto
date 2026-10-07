# 能力卡：nway_wilkinson

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：N-way Wilkinson 功分器（TA-4，树形 N=4）：输入馈线（port1，−BOARD 板边）→ 一级 T 叉（双 λ/4 臂 √2·Z0，x 向并列间距 G1=9mm，wilkinson GAP 口径）→ 50Ω 支线 → 二级双 T 叉（各叉臂间距 G2=5.5mm）→ 四路 50Ω 输出馈线（port2..5，+BOARD 板边）；隔离电阻 R=2·Z0 各臂端面跨接（LumpedElement ny=0，共 3 支）；全金属同层零交叉。拓扑选择：内核 star 分支（Pon 1961 浮点节点）单层 N≥3 不可布（浮点节点/Δ 环闭合路径必与边界馈线交叉）——渲染取 内核 tree 分支（阻抗级同源），N=2 与 wilkinson 模板同解、N≥8 超轮转管线规模（渲染守卫拒 n_way≠4）
- f0：2.5 GHz ｜ 端口：5 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：全 S 矩阵 5×5 @ .s5p（进程隔离激励轮转 5 run，#208 口径推广；openems_rotation n_ports 参数化；port1=输入、port2..5=输出 x=∓(XA1±XA2)）。裁判=内核 synthesize_nway_wilkinson(tree) 阻抗级：@f0 均分 −6.02dB（1/4 功率）、全端口匹配 |S11| 深谷、输出对隔离（每级 R=2·Z0 经典 2-way 单元级联保证）
- 参数：w_arm_mm, w_feed_mm, arm_len_mm, iso_r_ohm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| arm_len_mm | 18.1624 |
| iso_r_ohm | 100.0 |
| w_arm_mm | 0.6035 |
| w_feed_mm | 1.1134 |
- 名义参数来源：`docs/templates/nway_wilkinson/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 6：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、nway_wilkinson.arm_z_ohm.closedform-v1、nway_wilkinson.isolation_r_ohm.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `nway_wilkinson.arm_z_ohm.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：nway_arm_z_ohm = 70.7107 ohm；±0.0（identity）；证据：runs/ta12_schiffman_qwt
- `nway_wilkinson.isolation_r_ohm.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：nway_isolation_r_ohm = 100.0 ohm；±0.0（identity）；证据：runs/ta12_schiffman_qwt
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_arm_mm=λ/4 臂宽（√2·Z0=70.7107Ω HJ 精算，gysel 同源档）；w_feed_mm=50Ω 馈线/支线/输出线宽（1.1134，mline 同源档）；arm_len_mm=臂 λ/4 长（εeff=2.72456 精算 18.1624mm@2.5GHz）；iso_r_ohm=隔离电阻值（=2·Z0，LumpedElement R 值——进元件值不进导体几何，qwt z_load_ohm 同口径豁免）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；全部盒缘（叉臂带缘/T 条缘/电阻盒边/支线与输出馈线缘）+ 端口 junction 精确入网（#198）；显式近场线 10µm 地板（#349）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边（#154 前节）
- 冒烟现状：未冒烟（离线审计过，#212，test_sicl_nway_templates）；近似级别如实登记：①λ/4 臂窄带理想口径——T 叉/臂端电阻位结点寄生不进闭式裁判（gysel/branchline 同口径，离线裁判=skrf 理想 2-way 单元级联装配）；②隔离电阻 LumpedElement 零厚度集总（qwt 端接同法，寄生 L/C 未建模）；③star 分支单层不可布为渲染面拓扑约束（非内核语义变更）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- 失败模式坑账链（playbook 命中 17 条，坑号 #NNN 为 出处标记）：
  - `fdtd_truncation_artifact`（fdtd_truncation_artifact；坑：#262、#84、#266）——窄 FC 窗/NrTS 截断长脉冲 → |S11|>1 假象；max|S11|>1 先查截断再怀疑物理
  - `sparam_nonphysical_investigate`（sparam_nonphysical_investigate；坑：#262、#174）——无衰减证据时的保守候选：截断已排除才升级物理怀疑
  - `single_excitation_mask_semantics`（single_excitation_mask_semantics；坑：#314、#248）——单激励产物零填充/互易补齐元素不构成互易证据；全矩阵比对是假阳性指纹
  - `true_reciprocity_violation`（true_reciprocity_violation；坑：#314、#257）——独立已测对上的互易破坏才是真破坏
  - `hfss_cad_unite_failure`（hfss_cad_unite_failure；坑：#310、#285）——unite 返回 False/合并后对象数>1=金属网络不连通，馈电不导电
  - `hfss_sheet_compression_undecidable`（hfss_sheet_compression_undecidable；坑：#264、#122）——多轮网格/端口排查互差小且仍 UNDECIDABLE=建模路径可疑，非数据坏
  - `pyaedt_session_leak`（pyaedt_session_leak；坑：#265、#308）——退出未 release 占 HFSS 轨；杀前先看命令行
  - `pyaedt_geometry_selection_api`（pyaedt_geometry_selection_api；坑：#285、#308）——gRPC 通道损坏后 finally release 可能静默失败，先修对象引用
  - `excitation_zero_volume`（excitation_zero_volume；坑：#174）——全带 |S11|≈0dB 平推=死激励指纹
  - `grid_near_coincident_lines`（grid_near_coincident_lines；坑：#152、#349）——nm 级近重合线 → CFL 时间步塌缩多个量级，症状常在端口链下游
  - `fake_cost_degenerate`（fake_cost_degenerate；坑：#195、#118）——窄带谐振带内 max 是常数陷阱；谷深语义走显式指标名
  - `probe_window_low_confidence`（probe_window_low_confidence；坑：#283、#282）——探针盒 <2 格/中线不落线 → 端口链偏差混入噪声
  - `dissipation_power_mismatch`（dissipation_power_mismatch；坑：#218、#244）——功率守恒破坏先查建模量纲再查物理
  - `thermal_model_implausible`（thermal_model_implausible；坑：#233）——恒温陷阱=热源项未被消费的典型症状
  - `hfss_port_convention_gap`（hfss_port_convention_gap；坑：#285、#307、#282、#335）——两引擎对同一设计可方向相反地偏；单引擎归因不可外推
  - `judgment_gate_fail`（judgment_gate_fail；坑：#122、#345）——通用裁决失败候选——更具体族同击时以其为主
  - `run_execution_failed`（run_execution_failed；坑：#144、#295）——status=failed 的执行层失败；物理判读前先排除环境/路径问题
