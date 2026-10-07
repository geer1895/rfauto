# 能力卡：hairpin

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：发夹线带通（WP2.3 Tier1 滤波器族）：N 个 λg/2 半波谐振器折成 U 形沿 x 并排，相邻外臂平行耦合（缝 gap_mm）；输入/输出为 50Ω 抽头馈线（T 形，板边 x=∓BOARD 至首/末谐振器外臂，抽头位置 tap_frac 自开路端计）
- f0：2.5 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ MSLPort 1-2（发夹线 BPF：带内回波纹波 + 带外抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response）
- 参数：order, w_mm, arm_len_mm, arm_gap_mm, gap_mm, tap_frac
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| arm_gap_mm | 3.0 |
| arm_len_mm | 36.7799 |
| gap_mm | 1.1328 |
| order | 3 |
| tap_frac | 0.398159 |
| w_mm | 1.1117 |
- 名义参数来源：`docs/templates/hairpin/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=teaching（`docs/templates/<模板名>/meta.yaml` teaching.sensitivity_ranking；EP-5 口径：order 名次 + basis 依据，来自可复核闭式恒等式而非幅值——幅值分数待 `knowledge/sensitivity_rankings.yaml` 数据管线落档后重跑导出器上卡）

| 名次 | 参数 | 依据 |
|---|---|---|
| 1 | gap_mm | 耦合缝 k(gap) 强敏感（repo 真机图谱单调陡降：gap 0.65 处 k 极大 0.0155，名义 k=0.0515 所需缝更小） |
| 2 | arm_len_mm | λg/2 谐振 |S|≈1（恒等式；名义含真机修正 c_f0=1.0370） |
| 3 | tap_frac | 外部 Q 抽头敏感（repo B1 标定 c(τ)=1.37437−0.75218·τ 链） |
| 4 | order | 阶数=离散综合参数（Chebyshev g 值表驱动，非连续几何维） |
- 排序=teaching 名次全序（1..N 连续；人工 commit 写入，引用锚文本由 test_teaching_service 对 grounding 文件核验）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、hairpin.cheb_g.closedform-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `hairpin.cheb_g.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：hairpin_cheb_g = 1.0316 dimensionless；±5e-05（rounding_band）；证据：runs/w4_phase4/w4e
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：order=谐振器阶数 N，w_mm=谐振器/馈线宽（50Ω，skrf HJ 综合），arm_len_mm=展开中心线总长 λg/2（2·臂长+臂间距），arm_gap_mm=U 内两臂缝（边缘到边缘；须 ≳3×线宽量级，名义 3.0mm：同臂自耦 k_self(3.0)=0.0115 ≪ 互耦 0.0515，旧 1.0 的 k_self=0.0602 反超互耦致四轮真机 FAIL，2026-09-16 定版），gap_mm=相邻谐振器耦合缝（锚=等缝口径；非等 k 逐缝变体走 gaps_mm 列表，不进本 meta；**同向拓扑 gap→k 须经结构修正 c(gap)**：k_EM=c(gap)·k_KJ，c=0.12-0.26 且非单调、k_EM 上限 ~0.0155≪ KJ 名义 0.0515——相邻臂开路端对齐致电/磁耦合反号相消，core.coupled_microstrip.HAIRPIN_KGAP_TABLE_MM 真机表，2026-09-17 W4④；根修见 hairpin_alt 交替取向变体），tap_frac=抽头位置比例 τ=t/L_tot
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；全部臂缘/弯带缘/抽头缘精确入网（#198 精确入网）
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
