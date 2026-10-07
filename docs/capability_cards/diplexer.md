# 能力卡：diplexer

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：Diplexer LP+HP T 结（TA-5，一阶常阻互补对偶 CR 型）：输入 50Ω 馈线（port1=antenna， −BOARD 板边）→ 微带 T 结 → LPF 臂（+x：50Ω 短段+LumpedElement 串联 L 断口桥接+50Ω stub 至 +BOARD=port2）与 HPF 臂（−x 镜像，串联 C=port3）；集总元件 atten_pi 串臂同法（ny=0 断口桥接）； 全金属同层零交叉
- f0：2.5 GHz ｜ 端口：3 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21/S31 @ MSLPort 1-3 单激励 7 列 CSV（port1=antenna 公共口激励，port2=LP/port3=HP 探针；3 端口轮转 footer，#208 口径）。裁判=core.diplexer_compose 同参精确复算 + diplexer_verdict 四门：能量守恒（幺正性恒等式 ≤1e-8）、交越=fc（|S21|=|S31| 交点 ±tol）、通带 |S11|、互补亏缺； CR 一阶对闭式锚 S11≡0/|S21|²+|S31|²≡1/交越精确 fc
- 参数：w_feed_mm, l_lpf_nh, c_hpf_pf
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| c_hpf_pf | 1.2732 |
| l_lpf_nh | 3.1831 |
| w_feed_mm | 1.1134 |
- 名义参数来源：`docs/templates/diplexer/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 6：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、diplexer.crossover_ghz.closedform-v1、diplexer.s21_power_f0.closedform-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `diplexer.crossover_ghz.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：diplexer_crossover_ghz = 2.5 GHz；±0.0（identity）；证据：runs/ta12_schiffman_qwt
- `diplexer.s21_power_f0.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：diplexer_s21_power_at_f0 = 0.5 dimensionless；±0.0（identity）；证据：runs/ta12_schiffman_qwt
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_feed_mm=全臂 50Ω 馈线/连接线宽（nominal_width_mm 单源）；l_lpf_nh=LPF 臂串联电感（=Z0/ωc， 内核 element_values 单源，LumpedElement L 值——进元件值不进导体几何，qwt z_load_ohm 同口径豁免）； c_hpf_pf=HPF 臂串联电容（=1/(ωc·Z0)，对偶值同口径豁免）。f0=交越频率 fc（meta f0_ghz）；元件位置/断口长为版图常量（近端 4mm/断口 0.4mm，电小寄生段口径）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；全盒缘（馈线/T 条/臂带缘/元件断口缘）+ 端口 junction 精确入网（#198）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边（#154 前节）；#347 输入段测量面-激励分离守卫
- 冒烟现状：未冒烟（离线审计过，#212，test_diplexer_ridged_templates）；近似级别如实登记：①理想集总 LumpedElement（无寄生 L/C/自谐振——2.5GHz 下 nH/pF 级元件自谐振 ≫fc，PCB 集总现实口径如实登记）； ②元件间 50Ω 连接线/馈线 stub 电长度寄生不进闭式裁判（qwt 节间阶梯同口径，元件紧凑排布使寄生段电小）； ③≥2 阶对固有回损地板使其判读门不可判读——v1 取一阶 CR 对（20dB/dec 选择性为一阶固有）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
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
