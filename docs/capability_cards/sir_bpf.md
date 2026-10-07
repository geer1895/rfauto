# 能力卡：sir_bpf

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：λ/4 型接地 SIR 带通（§C3 滤波器族 II，MYJ SIR 章口径）：N 根阶梯阻抗棒平行排列（开路端低阻段 w_low + 接地端高阻段 w_high，步进比 Z_lo/Z_hi=35/70 给出紧凑化，谐振条件 tanθ1·tanθ2=Z_lo/Z_hi），同端接地顶端过孔 r=0.15mm，耦合区=低阻段（相邻棒低阻段对齐）；双 50Ω 馈线（板边段 w_feed + 耦合段 w_low 台阶）缝耦合自 y=−BOARD 板边引入（单轴 PML）
- f0：2.5 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ MSLPort 1-2（SIR 带通：带内回波纹波 + 带外抑制；裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限对照 C13 coupling_matrix_response 互证，实测 max|ΔS21|=0.0061dB）
- 参数：order, w_feed_mm, w_low_mm, w_high_mm, l_low_mm, l_high_mm, gaps_mm, feed_len_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| feed_len_mm | 53.3232 |
| gaps_mm | [0.2417,1.5189,1.5189,0.2417] |
| l_high_mm | 6.7818 |
| l_low_mm | 6.5719 |
| order | 3 |
| w_feed_mm | 1.1117 |
| w_high_mm | 0.6144 |
| w_low_mm | 1.8944 |
- 名义参数来源：`docs/templates/sir_bpf/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 6：c3.k_of_g.openems-hfss-v1、c3.l_via_h.openems-hfss-v1、coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `c3.k_of_g.openems-hfss-v1`（curve/active；引擎对 openems（hfss 仲裁））：k_of_g 曲线 6 点（横轴 g_mm）；±0.05（relative）；证据：runs/df6_a1_r4
- `c3.l_via_h.openems-hfss-v1`（constant/active；引擎对 openems（hfss 仲裁））：l_via_h = 1.25e-10 H；±2e-11（arbitration_interval）；证据：runs/df5_c3fix
- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：order=谐振棒数 N（决定 gaps_mm 列表长度 N+1，单独改 order 而不改列表=非法）；w_feed_mm=馈线板边段宽（50Ω HJ）；w_low_mm/w_high_mm=低阻/高阻段宽（HJ 精算 35Ω/70Ω，须 w_low>w_high）；l_low_mm=低阻段物理长（电长 6.7941 − 开路端 Δl 0.2222，裁判以等效长度回代）；l_high_mm=高阻段物理长（接地端无 Δl；理想短路口径 7.1055mm − 登记⑨+R1 校准过孔缩短 0.3237mm = 6.7818mm）；gaps_mm[j]=第 j 缝边到边（低阻耦合区，同索引同语义，#154）；feed_len_mm=板边到棒阵列底端馈段长
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；棒/馈/台阶缘+过孔中心精确入网（#198 精确入网）
- 冒烟现状：真机 openEMS 冒烟后置（followUp，循 coupled_bpf NrTS PARTIAL 先例），本项全程离线验收
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
