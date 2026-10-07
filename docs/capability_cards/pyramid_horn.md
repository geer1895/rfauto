# 能力卡：pyramid_horn

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：标准增益角锥喇叭：WR-90 波导馈电直管（端口面贴 y=−DOM_Y PML_8 域边）+ 四壁 梯形口径段（喉部 y=0、口径 y=l_flare；H 面宽沿 x a→a1、E 面高沿 z b→b1）； 斜壁以 8 段矩形截面阶梯链逼近（段间框面闭合=全 PEC 封闭腔）；空气填充无介质 板，y 轴双端 PML_8、x/z MUR
- f0：10.0 GHz ｜ 端口：1 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ RectWGPort 1（解析 TE10 模式端口，Z_ref=解析波导阻抗 ZL=k·Z0/β 口径）； 增益判读=口径场闭式（core/horn_synthesis）对照，方向图/nf2ff=Ph3 真机窗
- 参数：a_mm, b_mm, a1_mm, b1_mm, l_feed_mm, l_flare_mm
- 基板：{"er":1.0,"h_mm":0.0,"tan_d":0.0}

## 名义参数

| 参数 | 名义值 |
|---|---|
| a1_mm | 76.40094536120978 |
| a_mm | 22.86 |
| b1_mm | 57.54769444861163 |
| b_mm | 10.16 |
| er | 1.0 |
| h_mm | 0.0 |
| l_feed_mm | 60.0 |
| l_flare_mm | 45.48234099926676 |
- 名义参数来源：`docs/templates/pyramid_horn/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=teaching（`docs/templates/<模板名>/meta.yaml` teaching.sensitivity_ranking；EP-5 口径：order 名次 + basis 依据，来自可复核闭式恒等式而非幅值——幅值分数待 `knowledge/sensitivity_rankings.yaml` 数据管线落档后重跑导出器上卡）

| 名次 | 参数 | 依据 |
|---|---|---|
| 1 | l_flare_mm | 轴向长经 σ=√(a1(a1−a)/(2λl)) 直接进入口径效率/增益（Orfanidis 21.4.3 链） |
| 2 | a1_mm | 口径宽边=口径面积主项（G∝e·A）+ 设计方程联立自洽 |
| 3 | b1_mm | 口径窄边（E 面同链 δ_E=λ/4） |
| 4 | a_mm | WR-90 波导口径（TE10 馈电边界条件，非自由综合维） |
- 排序=teaching 名次全序（1..N 连续；人工 commit 写入，引用锚文本由 test_teaching_service 对 grounding 文件核验）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、pyramid_horn.gain_db.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `pyramid_horn.gain_db.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：pyramid_horn_gain_db = 15.0 dB；±0.0（identity）；证据：runs/review_ge8e/x5_analytic_anchors、runs/real_machine_window/w7a
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：a_mm=波导口宽边（H 面，x 向，WR 口径）；b_mm=波导口窄边（E 面，z 向）； a1_mm=口径宽边（H 面，综合目标增益下 Orfanidis(21.5.1)+Balanis δ_H=3λ/8 设计方程解）；b1_mm=口径窄边（E 面，δ_E=λ/4 同链）；l_feed_mm=馈电直管 最短长（实际管长=max(l_feed, l_flare+λ0/4+4mm) 口径侧空气域自动保证）； l_flare_mm=喇叭轴向长（同设计链）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50（空气口径，官方 base 级）；NEAR=base/4；全部壁面站线（波导口缘/逐段截面缘/阶梯框/口径面/端口面） 显式入网（#198）+ 全轴 1µm 近重合去重（#152）；渲染守卫：阶梯步距 ≥4·NEAR （#266 族）、a1>a 且 b1>b；口径侧空气域 ≥λ0/4+4mm 由管长自动外推保证 （#174 族）
- 冒烟现状：未冒烟（离线审计过，#212，test_pyramid_horn_template）；近似级别如实登记： ①斜壁 8 段阶梯化（矩形截面链，段中截面采样）；②闭式口径面模型不含壁损耗/ 口面反射/边缘绕射；③方向图/nf2ff 与真机冒烟=Ph3 窗（本批零发射）
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
