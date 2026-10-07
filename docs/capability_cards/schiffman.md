# 能力卡：schiffman

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：Schiffman 90° 定差移相器（TA-1）：耦合段=远端桥接平行耦合 U 形全通段（C-section：双带条 x=±(gap/2+w/2) 沿 y、远端桥带闭合，port1/2 在 −BOARD 板边近端）+ 参考直通段（50Ω，长 l_ref，port3/4 在 ±BOARD 板边）；双路径同板 DC 隔离（净空 ≥3·h_sub）；全通匹配 Z0e·Z0o=Z0²=2500 由设计链构造保证
- f0：2.5 GHz ｜ 端口：4 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：全 S 矩阵 4×4 @ .s4p（官方激励轮转 4 run，#208 口径同 ratrace/lange；port1/2=耦合段两端、port3/4=参考段两端）。裁判=core.synthesis.schiffman_delta_phase 闭式：Δφ(f)=deg(unwrap∠S43)−deg(unwrap∠S21)（两路径测量面经 MeasPlaneShift 解嵌到段端面），@f0=+90°、带内平坦度对照 kernel phase_flatness；openEMS DFT e^{−jωt} 口径（#253②），skrf 装配侧符号取反如实换算
- 参数：w_mm, gap_mm, l_coupled_mm, l_ref_mm, w_ref_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| gap_mm | 0.0692 |
| l_coupled_mm | 18.192633 |
| l_ref_mm | 54.577898 |
| w_mm | 0.9051 |
| w_ref_mm | 1.1134 |
- 名义参数来源：`docs/templates/schiffman/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、schiffman.delta_phase.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `schiffman.delta_phase.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：schiffman_delta_phase_deg = 90.0 deg；±0.0（identity）；证据：runs/ta12_schiffman_qwt
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_mm=耦合段带条宽（Z0e/Z0o 经 KJ 反解联动，schiffman_design_params 单源）；gap_mm=耦合缝宽（同 KJ 反解；ρ=Z0e/Z0o 名义 2.0——低 εr 可达域上限见 nominal_derivation）；l_coupled_mm=耦合段长（θ0=ratio·90° 电长度闭式，ratio=1 经典 λ/4 耦合段）；l_ref_mm=参考段长（Δφ=90° 目标对 L_ref 线性一步反解，Schiffman 3L 惯例语义由内核解出实际值）；w_ref_mm=参考段/馈线宽（50Ω HJ 精算）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；耦合缝 0.0692mm<NEAR 按 #311 缝中点精确入网（x=0 中线+±gap/2 带缘精确 AddLine，缝内内部线 ≥1 恒成立，不设 NEAR≤gap/3 硬守卫——C4 决议口径）；耦合对四带缘/桥带缘/段两端/参考段两端/参考带缘精确入网（#198）；真机建议显式 mesh_resolution_mm≤0.3（缝邻域分辨）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边（#154 前节）
- 冒烟现状：未冒烟（离线审计过，#212，test_schiffman_qwt_templates）；近似级别如实登记：①准静态 εeff 逐模常数化无色散（内核 v1 声明）；②参考段 εeff 取偶/奇模相速平均口径（内核 v1）；③测量面解嵌到段端面，端面孤立线↔耦合对阶跃寄生不建模（Schiffman 原文口径）；④ρ=2.0 平坦度 ±25% 窗 max 偏差 ≈7.2°（低 εr 可达域内，不凑 ρ=3）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
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
