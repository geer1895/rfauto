# 能力卡：ring_resonator

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：微带环形谐振器（F-A M3 材料提取 fixture）：闭环环带（r_mean±w/2，逐网格行 栅格化，ratrace 同法 #198 零台阶）+ 径向对置双 50Ω 间隙耦合馈线（x=0 沿 y， 端口面贴 y=±BOARD PML_8 域边）；对置 180° 馈点对各次模均为场腹（全 n 模可 激励）；z-min PEC 地 + 缺省 rogers4350b 叠层（guided 口径）
- f0：2.5 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ MSLPort 1-2（环形谐振器：S21 谐振指纹 f_n≈n·c/(2πr_mean·√εeff) 反演 εr；1/Q_L=1/Q_d+1/Q_c+1/Q_r 分离提取 tanδ——F-A M3 口径，提取内核 core/dielectric_extract 属后续批次）
- 参数：r_mean_mm, w_mm, gap_mm, feed_w_mm
- 基板：{"er":3.66,"h_mm":0.508,"tan_d":0.0037}

## 名义参数

| 参数 | 名义值 |
|---|---|
| feed_w_mm | 1.1134 |
| gap_mm | 0.4 |
| r_mean_mm | 11.299802692199101 |
| w_mm | 1.1134 |
- 名义参数来源：`docs/templates/ring_resonator/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、ring.design_dk.openems-hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `ring.design_dk.openems-hfss-v1`（pointer/experimental；引擎对 openems（hfss 仲裁））：ring_design_dk_dev 双值 hfss=3.342460048981009 / openems=3.5332928518364177 dimensionless（不取平均，#122）；±0.13（engine_pair_spread）；verdict DISAGREE；证据：runs/ge5_fa3_dk、runs/oe_phase3/ring_tier2_gap020
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：r_mean_mm=环平均半径（谐振尺度：闭环周长 2πr_mean=n·λg；名义值由 f1 经 HJ εeff 反解 c/(2πf1√εeff)，ring_resonator_design_params 单源）；w_mm=环带 线宽（50Ω HJ 口径 1.1134mm，εeff 随之）；gap_mm=馈线-环带间隙（间隙电容 耦合 v1 口径，决定 Q_c/抽头强度）；feed_w_mm=50Ω 馈线宽（HJ 精算）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）——本 模板缺省自动档触发缝分辨守卫（NEAR=0.285mm>gap/3），须显式 mesh≤4·gap/3 （C3 族同口径）；环带基点缘/馈线带缘/馈端与缝缘精确入网 + 缝中线入网 （#198/#311）；渲染守卫：NEAR≤gap/3（#266 族缝分辨）、feed_len≥42·NEAR （#347 族 MeasPlaneShift-FeedShift 分离）、r_in>0；全轴 1µm 近重合去重 （#152）；端口面贴 PML_8 域边（#154 前节）
- 冒烟现状：未冒烟（离线审计过，#212，test_ring_resonator_template）；近似级别如实 登记：v1 闭式未含色散/曲率修正与栅格化慢波补偿（ratrace_ring_mesh_k 两锚 定标于 70.7Ω 线宽未对本模板定标，禁止外推复用），εr 提取精度由 G2 闭环+ HFSS 仲裁另批兑现
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
