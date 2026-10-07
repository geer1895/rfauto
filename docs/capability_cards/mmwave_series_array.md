# 能力卡：mmwave_series_array

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：1×N 串馈毫米波阵（§18.3d C10d）：N 元共线沿 y（x=0 居中，L 沿 y/W 沿 x）， 相邻元以互联线接辐射边中心（互联长 s=自由设计参数，行波渐进相位 βg·s）； MSLPort 自 y=−DOM 入、自画馈段至链首元（feed_margin）；链末 stub+匹配集总 负载到地（R=线 Z0 一阶）——行波阵口径，与 C2 patch_array_series（λg/2 谐振式、链末开路）分族；基板 + z-min PEC 地，y 轴 PML_8
- f0：78.0 GHz ｜ 端口：1 ｜ 时长 ≤60.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ MSLPort 1（1×4 行波串馈贴片阵，链末 50Ω 集总匹配到地：谷位=单元谐振 设计式精确逆 patch_resonance_hj_ghz；方向图走 far_field=True nf2ff，离线 裁判=相位递推闭式主瓣指向 core/array_synthesis.series_feed_beam_direction_ cosine；未真机冒烟）
- 参数：n_elem, elem_len_mm, elem_w_mm, link_len_mm, feed_w_mm, feed_margin_mm, h_mm
- 基板：{"er":3.0,"h_mm":0.127,"tan_d":0.001}

## 名义参数

| 参数 | 名义值 |
|---|---|
| elem_len_mm | 0.9271 |
| elem_w_mm | 1.3589 |
| er | 3.0 |
| feed_margin_mm | 3.0 |
| feed_w_mm | 0.3259 |
| h_mm | 0.127 |
| link_len_mm | 1.7482 |
| load_r_ohm | 50.0 |
| n_elem | 4 |
| tan_d | 0.001 |
- 名义参数来源：`docs/templates/mmwave_series_array/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 6：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、mmwave.design_dk.ro3003-oe-hfss-v2、mmwave.design_dk.ro3003-oe-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmwave.design_dk.ro3003-oe-hfss-v2`（constant/active；引擎对 hfss（openems 仲裁））：mmwave_design_dk_ro3003 = 3.1025 dimensionless；±0.0132（engine_pair_spread）；verdict AGREE（三档 AGREE Δ=0.656%；budget 跳 SWF 走 R2 末扫=criteria R2 预声明）；证据：runs/ge7_hfsswin/dk78r、runs/df7_c10d
- `mmwave.design_dk.ro3003-oe-v1`（pointer/experimental；引擎对 openems（hfss 仲裁））：mmwave_design_dk_oe 双值 openems=3.1434 dimensionless（不取平均，#122）；±0.16（engine_pair_spread）；verdict REJUDGE_PASS（离线复判模型一致性 PASS——单引擎单点封档 experimental 非消费级 constant）；证据：runs/df7_c10d、runs/ge6_anchor
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：n_elem=单元数（≥2），elem_len_mm=单元谐振长 L（沿 y；Balanis Ch.14 c/(2f0√εeff)−2ΔL，fake 谷位为其精确逆），elem_w_mm=单元宽 W （c/(2f0)√(2/(εr+1))），link_len_mm=互联线长 s（行波渐进相位自由度： u0=(π+βg·s−2π)/(k0·d)，d=L+s；s=λg/2 退化为 C2 同相侧射），feed_w_mm=50Ω 馈线/互联宽（HJ 0.3259mm @78GHz），feed_margin_mm=板边到链首元馈段长 （MSLPort 自画，MeasPlaneShift=margin/3），h_mm=基板厚（毫米波板 0.127）； er/tan_d 走 substrate/nominal（RO3003 类）
- 网格：辐射器件：上方空气隙 λ0/4+、侧向至域界（MUR）；贴片/互联/stub/负载盒缘 精确入网（#198）；渲染守卫：NEAR≤feed_w/3（#266 族，线宽分辨）、 |MeasPlaneShift−FeedShift|≥3.9·NEAR（#347）；全轴 1µm 近重合去重（#152）； 端口面贴 PML_8 域边（#154 前节）
- 冒烟现状：未冒烟（离线审计过，#212，test_mmwave_series_array_template）；真机发射面= 预算预声明 runs/df7_c10d/criteria.md §d（0.1mm 格 ~3.6e7 cells、 dt~4.8e-14s、NrTS~2.5e4、墙钟数小时～半天/点，发射前以 exec 实测为准）， 本批零发射
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
