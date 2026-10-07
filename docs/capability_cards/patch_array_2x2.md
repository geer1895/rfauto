# 能力卡：patch_array_2x2

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：2×2 平面贴片阵（§10.3 C2）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 y=20∓dy/2；底排缺口向 −y 自下入，顶排缺口向 +y——馈线经 J1± 沿 y0 外走到元列外侧走廊 x=±(dx/2+W/2+2mm) 上行、顶排上方内折、变换段自上向下入缺口（同层零交叉）；H-tree 阻抗账同 1×4；基板 + z-min PEC 地
- f0：5.8 GHz ｜ 端口：1 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ LumpedPort 1（底探针馈 H-tree 2×2 贴片阵：谷位/谷深；方向图走 far_field=True nf2ff，离线裁判=平面阵可分离积 AF_x·AF_y 逐点；未真机冒烟）
- 参数：elem_len_mm, elem_w_mm, elem_feed_mm, spacing_x_mm, spacing_y_mm, feed_w_mm, q_w_mm, q_len_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| elem_feed_mm | 3.8717 |
| elem_len_mm | 12.9058 |
| elem_w_mm | 16.9311 |
| feed_w_mm | 1.112 |
| q_len_mm | 7.8217 |
| q_w_mm | 0.6025 |
| spacing_x_mm | 25.0172 |
| spacing_y_mm | 25.0172 |
- 名义参数来源：`docs/templates/patch_array_2x2/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、patch_array.f_res.openems-hfss-v1（core/anchors；通配 + 专属）
- 健康门：效率窗门 η∈[0.55, 0.79]（ui_service.PATCH_ETA_GATE；#274 模板作用域：仅 patch 族适用）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `patch_array.f_res.openems-hfss-v1`（pointer/experimental；引擎对 openems（hfss 仲裁））：patch_array_f_res_dev_pct 双值 hfss=5.6898 / openems=4.976 GHz（不取平均，#122）；±14.344855（arbitration_interval）；verdict DISAGREE；证据：runs/hfss_window_b2a/patch_array_2x2
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：elem_len_mm=单元谐振长 L（沿 y；Balanis Ch.14 传输线模型 c/(2f0√εeff)−2ΔL，fake 谐振为其精确逆），elem_w_mm=单元宽 W（沿 x；c/(2f0)√(2/(εr+1))，决定 εeff/ΔL 与 H 面波束），spacing_x_mm/spacing_y_mm=元列/元排中心距（均 0.484λ0=25.0172mm；可分离栅格），feed_w_mm=50Ω 线宽（主干/透明连线/缺口内馈段；HJ 1.112mm），q_w_mm=70.7Ω λ/4 变换段宽（HJ 0.6025mm），q_len_mm=变换段长 λ/4=c/(4f0√εeff(q_w))=7.8217mm（J0→J1± 与各元入缺口最后一段共用），elem_feed_mm=插入馈深度 y0（缺口深=馈线终点=馈点；Rin(y0)=Rin(0)cos²(πy0/L)，0.3L≈100Ω 口径）
- 网格：辐射器件：上方/侧向空气隙 λ0/4；全部盒缘精确入网（#198）
- 冒烟现状：未真机冒烟（2026-09-15 注册，离线审计/闭式裁判已过）。openEMS 轨 followUp：scripts/smoke_array_anchor.py <template>，判据=S11 谷位 f0±12% 窗（谷深 ≤−6dB）+ far_field nf2ff 主瓣天顶/HPBW·Dmax 对照 core/array_synthesis 闭式 ≤20-30% + η=Prad/P_acc 合理；预算 NrTS=100000 分钟~小时级，逐模板串行单飞
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
