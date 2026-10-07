# 能力卡：ridged_wg

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：空气单脊矩形波导均匀段（TA-6）：脊段外廓 a×b+顶壁居中脊 s×d（y∈±l_ridge/2）+ 两端加宽馈波导 a_feed×b（H 面对称阶跃，a_feed=c/(2·0.75·fc_ridge) 结构性 >4a/3）+ 阶跃端面框板闭合（零泄漏）； 双 RectWGPort 打在馈段（激励/探针面均内移 16·BASE 出 PML_8）；空气填充全金属（无介质板）
- f0：5.2 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ RectWGPort 1-2（解析 TE10 打在加宽馈段，Z_ref=解析波导阻抗；S21=port2.uf_inc 口径——自然升序定义端口透射在 uf_inc，coax_wg 同款）。判读锚（预声明，真机窗）：①交越膝点 |S21| −3dB 落内核 fc·(1±8%)（脊段消逝衰减 @0.8fc≈22dB/40mm 使过渡陡峭）；②带底消逝衰减斜率对照 evanescent_attenuation_db； ③带内 |S21| 平台≈1（馈段/脊段单模行波）。内核裁判=ridged_waveguide.cutoff_fc_hz 同参复算（XC-P 精度域 g/b≥0.4，名义 0.454）
- 参数：a_mm, b_mm, s_mm, d_mm, l_ridge_mm, l_feed_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| a_mm | 22.86 |
| b_mm | 10.16 |
| d_mm | 5.5434 |
| er | 1.0 |
| h_mm | 0.0 |
| l_feed_mm | 25.0 |
| l_ridge_mm | 40.0 |
| s_mm | 9.144 |
- 名义参数来源：`docs/templates/ridged_wg/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 6：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1、ridged_wg.evanescent_atten_db_0p8fc.closedform-v1、ridged_wg.fc_ghz.closedform-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `ridged_wg.evanescent_atten_db_0p8fc.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：ridged_wg_evanescent_atten_db = 21.85 dB；±0.05（rounding_band）；证据：runs/ta12_schiffman_qwt
- `ridged_wg.fc_ghz.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：ridged_wg_fc_ghz = 5.0 GHz；±0.0（identity）；证据：runs/ta12_schiffman_qwt
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：a_mm/b_mm=脊段外廓宽/窄边（b/a=0.5 标准档）；s_mm=脊宽（s/a=0.4 档）；d_mm=脊深（design_ridge_depth 对 fc_target=5.0GHz 反解，名义 g/b=0.454 落 XC-P 精度域 ≥0.4；g=b−d 单脊）；l_ridge_mm=脊段长（40mm→消逝衰减 ≈22dB@0.8fc）；l_feed_mm=单侧馈段最短长（实际域长自动外推保端口两面+余量，horn 同款）；er=1.0/h_mm=0.0 为空气填充占位键（MATERIAL_VALUE_PARAMS 豁免）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50（空气口径，horn 同款）；全部壁面站线（外廓缘/脊缘/馈段缘/阶跃框/端口面）显式入网（#198）+ 全轴 1µm 近重合去重（#152）；渲染守卫：NEAR ≤ min(s,g)/3（#266 族特征分辨）、g/b≥0.4（XC-P 精度域）、判读带 ⊂（fc_feed, min(1.5·fc_ridge, 外廓 TE10)）单模域
- 冒烟现状：未冒烟（离线审计过，#212，test_diplexer_ridged_templates）；近似级别如实登记：①一阶横磁共振闭式遗漏脊缘杂散电容（kc 高估 +1.5~+8% @g/b≥0.4 分档域，内核精度档案 WARN）；②H 面阶跃结反射不进闭式裁判（v1 直阶跃无渐变——工程实践为 λ/4 锥削过渡，后续变体）；③RectWGPort 打在馈段，脊模经阶跃结的耦合损耗计入 S21；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
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
