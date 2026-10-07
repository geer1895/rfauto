# 能力卡：siw

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：直 SIW 传输线段：基板 z∈[0,h] 上下显式零厚金属板（贴 z 边界 PEC）+ 两列 金属化过孔 PEC 圆柱（x=±w/2、心距 s、全域精确栅格、藩篱直入 PML=匹配 端接）；端口=两端 LumpedPort z 桥（中线、跨全高、盒边入网、16·BASE 出 PML_8）；域 x 半宽=w/2+w_eff/2（侧界 MUR 吸收泄漏）、y 半宽=line_len/2+ 16·BASE（PML_8）——矩形域，BOARD=60e-3 不适用（机制层 DOM_X/DOM_Y 字面注入）
- f0：10.0 GHz ｜ 端口：2 ｜ 时长 ≤45.0 ns ｜ 网格档：0.0 mm
- 提取口径：LumpedPort z 桥×2（R=闭式 Z_PV=2b·Z_TE/w_eff，CalcPort 同参考）： 原始 S=带载比值（#250 口径，slotline_lumped 同）；β/εeff 主判=S21 解缠 相位斜率÷port_beta.csv 实测 plane_dist（cps 同契约，LumpedPort 无 β 属性）；fc10 由带内 φ(f)=−β(f；fc)·L+φ0 单参数拟合（OE 锚 G1，预声明 runs/siw_family/criteria.md §6）
- 参数：w_mm, d_mm, s_mm, line_len_mm
- 基板：{"er":3.66,"h_mm":0.508,"tan_d":0.0037}

## 名义参数

| 参数 | 名义值 |
|---|---|
| d_mm | 0.6 |
| er | 3.66 |
| h_mm | 0.508 |
| line_len_mm | 63.0724 |
| s_mm | 1.0 |
| tan_d | 0.0037 |
| w_mm | 12.1317 |
- 名义参数来源：`docs/templates/siw/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、siw.fc_te10_ghz.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `siw.fc_te10_ghz.closedform-v1`（constant/active；引擎对 closedform（None 仲裁））：siw_fc_te10_ghz = 6.6667 GHz；±0.0001（rounding_band）；证据：runs/review_ge8e/x5_analytic_anchors、runs/real_machine_window/w7a
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_mm=两过孔列心距（物理宽度，Cassivi 等效宽度 w_eff=w−d²/(0.95s) 的输入）、 d_mm=过孔直径、s_mm=过孔心距（渲染按全域 k·s 精确栅格）、line_len_mm= 两端口测量面间距（名义 3λg@f0 闭式精算）；h/er/tan_d 走 substrate/nominal （TE10 截止与 β 与 h 无关，Microwaves101 SIW 条目）
- 网格：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；全域 NEAR=base/4 （SmoothMesh 全轴均匀化实测）；过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线 （#311 类比）、显式近场线 10µm 地板（#349）、端口盒 ≥2 格且中线落格 （#283，生成期断言）、基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）
- 冒烟现状：离线审计先行（#212，test_siw_template）；真机锚已落判（df4f：G1 勘误 PASS/G2 PASS/G3 口径裁定/G4 PASS，runs/siw_family/，驱动 scripts/siw_anchor_smoke.py）；预声明门与预算见 runs/siw_family/criteria.md §6
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
