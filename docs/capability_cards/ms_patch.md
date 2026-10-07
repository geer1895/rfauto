# 能力卡：ms_patch

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：反射阵方贴片单元：接地基板（z 底 PEC 边界）+ 零厚方贴片；单胞方形域 x 对壁 PEC / y 对壁 PMC（TEM 平面波，官方 Parallel Plate Waveguide 教程 口径）；贴片上方 λ0/4 空气区置双 E 探针对（自由悬浮无源）+ 探针对上方 soft plane 激励面，域内零电阻片
- f0：10.0 GHz ｜ 端口：1 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ 双 E 探针对反射分解（soft plane 激励 exc_type=0；探针对=贴片上方空气区 2 只全口径 E 线探针，对内距 λ0/16，精确 β=2πf/c 分解 F/B 后 _WgProbePairRefl 对调 uf——入射=−z 照明波、反射=+z 回波，footer 契约/S 列 schema 不变， _port2=_port1 别名 S21 列≡S11）。波导模拟器≡无限阵@θ=0，E∥x 极化前提； |S11|≈1 的 argΓ 逐 px 入反射相位 LUT（探针面去嵌相位常数项不进扫 px 差分）； 健康判据=|Γ| 线性域 ≈1（空波导标定 EN=|Γ|²≈1.0 平坦）。无耗接地结构幅度 读出 «1 = 读出判废信号。（2026-10-01 ge5 ms_patch 读出修复：原全口径 LumpedPort 电阻片=测量面并联 Z0 负载，反射相位为片负载 Möbius 像， runs/ge5_msjcross/audit.md §D/E）
- 参数：px_mm, py_mm, period_mm, h_mm
- 基板：{"er":3.66,"h_mm":1.524,"tan_d":0.0037}

## 名义参数

| 参数 | 名义值 |
|---|---|
| er | 3.66 |
| h_mm | 1.524 |
| period_mm | 14.9896 |
| px_mm | 8.5406 |
| py_mm | 8.5406 |
| tan_d | 0.0037 |
- 名义参数来源：`docs/templates/ms_patch/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

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

- 参数语义：px_mm=E 向（x）谐振边长（LUT 扫描变量），py_mm=非谐振宽（y）， period_mm=单胞周期（方形域边长），h_mm=基板厚；er/tan_d 走 substrate/nominal（材料属性不改导体）
- 网格：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；贴片缘精确入网 +胞缘缝 3+ 中点入网（#311）；NEAR≤最小胞缘缝/3 渲染期守卫（#266）； 全轴最小网格间距 ≥10µm
- 冒烟现状：离线审计先行（#212，test_metasurface_templates）；波导模拟器扫描战役 （粗 21+细 41 点）发射面见 战役任务书；读出修复后重扫 见 runs/ge5_j2fb/（J2 fallback 战役段②）；J1c 相位覆盖 ≥300° 与 J4 HFSS Floquet 锚属真机轨
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
