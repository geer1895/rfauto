# 能力卡：ratrace

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：rat-race 环形电桥（WP2.3：环周长 1.5λg@70.7Ω，arcs λ/4×3+3λ/4；规范角位 Σ=0°/out1=60°/Δ=120°/out2=300°——out1/out2 分居 Σ 两侧 λ/4，大弧 3λ/4 扫 Δ→out2 之间（pt5 实测定版）——三端口挤 上半区，下半区是大弧；out1/Δ 径向馈+弯折竖直引出）
- f0：2.5 GHz ｜ 端口：4 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：全 S 矩阵 4×4 @ ratrace.s4p（官方激励轮转 4 run：SetEnabled 逐端口激励+匹配终端探针；skrf Touchstone 主路，CSV 降兼容）。裁判=理想 180° 混合环 S 矩阵闭式（#208 Y 矩阵推导）：Σ 均分 -3dB 同相、Δ 隔离、out1↔out2 互隔离；规范角位 Σ=0°/out1=60°/Δ=120°/out2=180°
- 参数：w_ring_mm, w_feed_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| r_ring_mm | 17.344 |
| w_feed_mm | 1.1134 |
| w_ring_mm | 0.604 |
- 名义参数来源：`docs/templates/ratrace/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=teaching（`docs/templates/<模板名>/meta.yaml` teaching.sensitivity_ranking；EP-5 口径：order 名次 + basis 依据，来自可复核闭式恒等式而非幅值——幅值分数待 `knowledge/sensitivity_rankings.yaml` 数据管线落档后重跑导出器上卡）

| 名次 | 参数 | 依据 |
|---|---|---|
| 1 | r_ring_mm | 1.5λg 恒等式 |∂lnf0/∂lnR|=1（精确） |
| 2 | er | f0 ∝ 1/sqrt(εeff) 恒等式 |
| 3 | w_ring_mm | 环宽经 εeff(w_ring) 进入周长（repo 综合链：λg 取环线宽自身 εeff） |
- 排序=teaching 名次全序（1..N 连续；人工 commit 写入，引用锚文本由 test_teaching_service 对 grounding 文件核验）

## 判据

- 锚覆盖 6：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、ratrace.r_ring_mm.closedform-v1、ratrace.ring_z_ohm.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `ratrace.r_ring_mm.closedform-v1`（constant/active；引擎对 closedform（None 仲裁））：ratrace_r_ring_mm = 17.344 mm；±0.001（rounding_band）；证据：runs/review_ge8e/x5_analytic_anchors、runs/real_machine_window/w7a
- `ratrace.ring_z_ohm.closedform-v1`（constant/active；引擎对 closedform（None 仲裁））：ratrace_ring_z_ohm = 70.7107 ohm；±0.0（identity）；证据：runs/review_ge8e/x5_analytic_anchors、runs/real_machine_window/w7a
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_ring_mm=环线宽（√2·Z0=70.7Ω 口径），w_feed_mm=四端口馈线宽（50Ω）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；环带逐网格行栅格化（零 #198 台阶误差）+ 馈线带缘精确入网；渲染半径 = 物理 R / k(BASE)（ratrace_ring_mesh_k：0.2/0.4mm 两锚 1.0877/1.1654 对 (k−1) 幂律内插、域外 clamp；HFSS 仲裁 2.465GHz 背书 MESH_ARTIFACT；柱坐标 k=1 为根治首选 #219/#232）
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
