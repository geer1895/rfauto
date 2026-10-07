# 能力卡：marchand_balun

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：Marchand 双槽臂最小族（底层五盒：外地 M1/M2、中条 M3、封口桥 M4/M5 与中条精确共边；顶层微带穿两槽+共享开路支节）：设计级结论=单支节串接已被两引擎互证证伪（四门 FAIL、两跨越点激励不对称、拓扑无隔离机制）——真 Marchand=两节对称耦合段（电路级综合 core/slotline_transitions.synthesize_marchand_two_section，名义点 50Ω→280Ω 差分、C=−7.02dB、(w,s,ℓ)=(1.7616,0.1016,18.4670)mm@h=1.524）；本模板保留作对照口径与判据载体，不作生产巴伦
- f0：2.5 GHz ｜ 端口：3 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：excite_port∈{1,2,3} 轮转（#208 进程隔离单激励）：P1 MSLPort 线基、P2/P3 LumpedPort 跨槽（抽头基线 RX/SRC 因子修正口径）；S23（隔离）需第二激励；巴伦判据门=BALUN_GATES（不平衡 ≤1dB、RL ≤−10、隔离 ≤−15、|S21| ≥−3.5）+ 相位极性约定如实报告
- 参数：w_slot_mm, x_port_mm, h_mm
- 基板：{"er":3.66,"h_mm":1.524}

## 名义参数

| 参数 | 名义值 |
|---|---|
| er | 3.66 |
| f0_ghz | 2.5 |
| h_mm | 1.524 |
| tan_d | 0.0037 |
| w_slot_mm | 1.0 |
| x_port_mm | 40.0 |
- 名义参数来源：`docs/templates/marchand_balun/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、marchand.f_null.openems-hfss-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `marchand.f_null.openems-hfss-v1`（pointer/experimental；引擎对 openems（hfss 仲裁））：marchand_f_null_dev_pct 双值 hfss=2.916 / openems=3.272 GHz（不取平均，#122）；±10.880196（arbitration_interval）；verdict DISAGREE；证据：runs/hfss_window_b2a/marchand_balun
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_slot_mm=槽宽，x_port_mm=P2/P3 距跨越区中心，h_mm=基板厚（模板参数，理由同 slotline）；f0 取自仿真频带中心
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50、NEAR=base/4；槽内缘/中条/封口桥共边网格线已钉（PEC 共棱连通）
- 冒烟现状：真机（a8abe8d）四门 FAIL 两引擎一致：不平衡 2.76/2.64dB、RL −7.4/−5.6、|S21| −4.05/−3.93、隔离 −0.55/−5.42、相位 −97°/−31°；幅度三量两引擎差 ≤0.2dB 互证=设计级结论成立。复跑冒烟只作回归对照，验收看两节新设计（followUp 立项）
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
