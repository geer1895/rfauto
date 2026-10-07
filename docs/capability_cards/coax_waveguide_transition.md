# 能力卡：coax_waveguide_transition

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：波导-同轴探针过渡：WR-90 矩形厚壁腔（a×b×l_wg，四壁+背短路板厚 wg_t，封闭 PEC 腔）+ 探针柱经底壁伸入腔内（针轴平行 TE10 E 场沿 y，针中心距背短路内侧面 backshort=λg/4）；port1=探针基 LumpedPort 集总桥（R=50Ω），port2=腔端面 RectWGPort 解析 TE10；z 轴双端 PML_8、x/y MUR
- f0：10.0 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S 参数 @ LumpedPort 1（探针基同轴截面集总桥，Z_ref=R=50Ω 实常数）+ RectWGPort 2 （解析 TE10，Z_ref=ZL=k·Z0/β 色散）；跨口传输含 sqrt(ZL1/ZL2) 阻抗校正（官方 wiki Coax-to-Waveguide 教程口径）；HFSS 仲裁=Ph3 窗
- 参数：a_mm, b_mm, l_wg_mm, wg_t_mm, pin_len_mm, pin_r_mm, port_h_mm, backshort_mm
- 基板：{"er":1.0,"h_mm":0.0,"tan_d":0.0}

## 名义参数

| 参数 | 名义值 |
|---|---|
| a_mm | 22.86 |
| b_mm | 10.16 |
| backshort_mm | 9.926779802778025 |
| er | 1.0 |
| h_mm | 0.0 |
| l_wg_mm | 30.0 |
| pin_len_mm | 5.588000000000001 |
| pin_r_mm | 0.5 |
| port_h_mm | 1.0 |
| wg_t_mm | 2.0 |
- 名义参数来源：`docs/templates/coax_waveguide_transition/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 4：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：a_mm=波导宽边（x 向，WR 表口径）；b_mm=波导窄边（y 向，WR 表口径）；l_wg_mm= 腔长（背短路内侧面 z=0 到腔端面）；wg_t_mm=壁厚（官方教程 2.0 直抄）； pin_len_mm=探针伸入深（壁内侧面起算，官方教程 0.55·b 比例档）；pin_r_mm= 探针截面半宽（官方教程 0.5 直抄）；port_h_mm=集总口隙高（壁内侧面到针底， 官方教程 1.0 直抄）；backshort_mm=探针中心距背短路内侧面（λg/4@f0 精算档）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50（空气口径，官方 base 级）；NEAR=base/4；全部壁面/探针特征站线（±a/2、±(a/2+wg_t)、±b/2、 ±(b/2+wg_t)、±pin_r、−b/2+port_h、−b/2+pin_len、背短路面、探针 z 缘、端口 校准面）显式入网（#198）+ 全轴 1µm 近重合去重（#152）；背面空气余量 6mm≈λ0/5（封闭腔无外漏场）
- 冒烟现状：未冒烟（离线审计过，#212，test_coax_wg_template）；近似级别如实登记：①探针柱 为矩形盒阶梯化（官方教程亦为矩形截面 pin，非圆柱）；②同轴连接器理想化为探针基 集总桥（官方 Python 教程口径，不含连接器体/介质填充）；③S21 跨口阻抗校正按 wiki 教程 sqrt(ZL1/ZL2) 一阶口径；④真机冒烟与 HFSS 仲裁=Ph3 窗（本批零发射）
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
