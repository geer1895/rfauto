# 能力卡：gysel

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：Gysel 高隔离功分器（1975 六节 λ/4 环，P2⑪ L-jog 等长拓扑重设计 2026-09-16）：P1—70.7Ω λ/4 臂—P2/P3；P2/P3—50Ω λ/4 隔离线（竖直段 YJ=iso_len−jog + 顶端横移 jog=|arm_len−iso_len| 保电长度）—Δ1/Δ2（x=±iso_len，各接 50Ω LumpedElement 端接，隔离负载外置）；Δ1—50Ω λ/2 桥带（跨度 2·iso_len=λ/2 精确，中点开路）—Δ2。矩形旧版（Δ 在角部、桥带继承 2·arm_len，+2.32% 二阶偏差）为历史口径（#211）
- f0：2.5 GHz ｜ 端口：3 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21/S31 @ MSLPort 1-3 + S23 第二激励（输出互隔离，标准双激励 footer 同 wilkinson）。裁判=理想 Gysel 环 S 闭式（#206 理论核验轮，skrf 六段线+双负载装配 @f0）：均分 -3.01dB 同相、全端口匹配、P2↔P3 互隔离
- 参数：w_arm_mm, w_feed_mm, arm_len_mm, iso_len_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| arm_len_mm | 18.162 |
| iso_len_mm | 17.75 |
| w_arm_mm | 0.6035 |
| w_feed_mm | 1.1134 |
- 名义参数来源：`docs/templates/gysel/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=9 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | arm_len_mm | 1.0 |
| 2 | w_arm_mm | 0.033755 |
| 3 | iso_len_mm | 0.0 |
| 4 | w_feed_mm | 0.0 |
- 排序=R9 commitment_order（optimization/eipu；高敏感先钉死，平局按参数名升序）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、gysel.s32_iso.openems-hfss-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `gysel.s32_iso.openems-hfss-v1`（constant/active；引擎对 openems（hfss 仲裁））：gysel_s32_iso_dev_db = 1.203787 dB；±5.0（arbitration_interval）；verdict AGREE_JUDGE；证据：runs/hfss_window_b2a/gysel
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_arm_mm=70.7Ω 臂宽（√2·Z0，skrf HJ 精算 0.6035mm），w_feed_mm=50Ω 馈线/隔离线/桥带宽（1.1134mm），arm_len_mm=臂 λ/4（εeff=2.7246 → 18.162mm@2.5GHz），iso_len_mm=隔离线 λ/4（50Ω εeff=2.8527 → 17.750mm）。派生量（不入参数表）：jog=|arm_len−iso_len|=0.412mm、YJ=iso_len−jog=17.338mm、Δ 节点 x=±iso_len → 桥带跨度=2·iso_len=35.500mm=50Ω λ/2 精确（L-jog 变体口径，电路级 @f0 S32/S11 ≤-88dB 装配实测）。历史事实：矩形旧版桥带继承 2·arm_len=36.324mm，对 λ/2 有 +2.32% 二阶偏差（矩形环 2 个自由边长不能同时满足三个 λ/4 约束；#211 真跑 S32=-32.6dB PASS 实证为二阶效应；P2⑪ 离线审计电路级归因：该偏差把 @f0 S32/S11 封顶 -34.8dB，为主因，junction 台阶/双臂对称性为二阶），本变体消除之。守卫：YJ>0（arm_len<2·iso_len）否则渲染 ValueError
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；三带缘+jog 顶边带缘+Δ 节点负载盒边精确入网（#198）；jog 横移 0.412mm ≈1 网格胞（0.4mm 档），Δ 缘与竖边带缘最小间距=jog≫1µm（#152 守卫）
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
