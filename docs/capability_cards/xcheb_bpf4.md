# 能力卡：xcheb_bpf4

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：交叉耦合开路环四重奏（TA-14）：四个 λg/2 方形开路环 2×2 排布（环1 左上/2 右上/3 右下/4 左下）；耦合=1-2 顶行水平缝 + 2-3 右侧竖缝 + 3-4 底行 水平缝 + **4-1 左侧竖缝（非相邻交叉耦合，cm_core folded m14 映射）**；馈电 =环 1/4 左边抽头（50Ω 馈线自 x=−BOARD 板边，hairpin A1 去嵌口径）
- f0：2.5 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ MSLPort 1-2（交叉耦合开路环 BPF：带内回波纹波+带外抑制+ **有限传输零点**（TZ，交叉耦合指纹）；裁判=C13 耦合矩阵闭式 coupling_matrix_response（cm_core 折叠矩阵消费），缝→k 纯 KJ+χ 一阶部分长标度）
- 参数：w_mm, a_mm, g12_mm, g23_mm, g34_mm, g14_mm, g_open_mm, g_pos_mm, tap_t_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| a_mm | 8.7626 |
| er | 3.66 |
| g12_mm | 0.3581 |
| g14_mm | 1.6526 |
| g23_mm | 0.4253 |
| g34_mm | 0.2885 |
| g_open_mm | 0.3 |
| g_pos_mm | 6.1338 |
| h_mm | 0.508 |
| tan_d | 0.0037 |
| tap_t_mm | 8.1454 |
| w_mm | 1.1117 |
- 名义参数来源：`docs/templates/xcheb_bpf4/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、xcheb_bpf4.cheb_g.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `xcheb_bpf4.cheb_g.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：xcheb_bpf4_cheb_g = 1.1088 dimensionless；±5e-05（rounding_band）；证据：runs/w4_phase4/w4e
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_mm=环线宽（50Ω HJ 单源）、a_mm=环边段长（周长=4a=λg/2−2Δl）、 g12/g23/g34_mm=主线耦合缝（1-2/2-3/3-4，KJ 反解 k/χ）、g14_mm=**交叉耦合缝** （4-1，非相邻矩阵条目 m14 映射——本模板的存在理由）、g_open_mm=环开缝宽（开路 端）、g_pos_mm=环 1/4 开缝中心自自由边角偏置（Q_e 路径的一部分）、tap_t_mm=抽头 自角距离（Q_e 闭式 τ·周长−g_pos）；er/tan_d 走 substrate/nominal
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；#266 耦合缝 守卫 NEAR≤缝_min/3（layout 抛错拒渲染）；全部环边/开缝缘/馈线缘精确入网（#198） +四耦合缝中线入网（#311）；审计档 TEMPLATE_MESH_MM=0.35（NEAR=0.0875 ≤ 0.2885/3 过守卫）
- 冒烟现状：离线审计先行（#212，test_ta_wave_c_templates）；内核数字裁判三锚 （test_cross_coupled_map）：①全极点退化对 classical g 值闭式（独立综合路径， max rel dev 1.2e-5）②KJ 往返+矩阵频响一致性（max|ΔS|≤1e-6 实测 7.5e-7）③ TZ=[±2.0] 传输零点保持（−88dB 谷映射前后一致）；χ 一阶部分长耦合与环角/开缝 结构效应未经 EM 校准（hairpin c(gap) 同族待标定项，#122 如实登记）；真机冒烟 与 HFSS 仲裁属后续批次（本批零发射）
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
