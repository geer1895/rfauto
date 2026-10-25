# 能力卡：interdigital_cap

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：GaAs IPD 叉指电容：n 根指条 A/B 两排交错（A 排接左汇流排、B 排接右 汇流排，B 排指条外伸 e_tip 越 A 排指条端），两端馈焊盘+双 LumpedPort 水平桥隙（Port1 跨馈盘A-左排、Port2 跨右排-馈盘B，串联口径）；两排 导体 DC 隔离（梳齿互锁=定义性质，缝塌缩短路即红）；全域 MUR（电小 器件近场主导）
- f0：2.0 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S21/S11 @ LumpedPort 1/2（馈盘A-左排 / 右排-馈盘B 水平桥隙，R=50Ω CalcPort 同参考；串联提取：理想串联元 Z=2·Z0·(1−S21)/S21→低频段 C=−1/(ω·Im(Z))，与 em deembed 的 Z12 提取链同式——IDC 集总 C=去嵌后 173.5fF 实测路径；C±50%/SRF>2×f0 质量判据由 CALC 键 interdigital_capacitance 承载）
- 参数：n_fingers, lf_um, wf_um, sf_um, e_tip_um, h_mm
- 基板：{"er":12.9,"h_mm":0.1,"tan_d":0.0006}

## 名义参数

| 参数 | 名义值 |
|---|---|
| e_tip_um | 15.0 |
| er | 12.9 |
| h_mm | 0.1 |
| lf_um | 220.0 |
| n_fingers | 24 |
| sf_um | 5.0 |
| tan_d | 0.0006 |
| wf_um | 5.0 |
- 名义参数来源：`docs/templates/interdigital_cap/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=17 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | lf_um | 1.073176 |
| 2 | n_fingers | 1.043532 |
| 3 | sf_um | 1.0 |
| 4 | er | 0.928053 |
| 5 | e_tip_um | 0.073168 |
| 6 | h_mm | 0.0 |
| 7 | tan_d | 0.0 |
| 8 | wf_um | 0.0 |
- 排序=R9 commitment_order（optimization/eipu；高敏感先钉死，平局按参数名升序）

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

- 参数语义：n_fingers=总齿数 N（渲染取整，≥2 且 A/B 排各半），lf_um=齿长 L （μm），wf_um=齿宽 W（μm），sf_um=齿间距 S（μm），e_tip_um=B 排尖部 外伸（μm，Clears 左汇流排、不产生相邻缝；闭式耦合长度 l_c=lf−e_tip）， h_mm=基板厚（仓内基板惯例 mm，GaAs 100μm 档）；er/tan_d 走 substrate/nominal（GaAs 半绝缘）——N/L/W/S 全 μm 为 IPD 工艺口径， 经 core.stackup.to_mm(v,'um') 单源换算（μm 帮手函数）；汇流排宽=wf、 馈盘宽=3·wf（派生值不单列参数）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 max(wf,sf,port_gap)/4 （μm 尺度几何驱动网格，禁 λ_sub/50 口径）；齿缘/汇流排/馈盘/端口盒 边+中线精确入网（#198）；NEAR≤min(sf,port_gap)/3 渲染期守卫（#266）； 全轴 1µm 近重合去重（#152）；端口盒三向 ≥NEAR 厚、激励向 ≥2 格 （#174/#283）
- 冒烟现状：未冒烟（离线审计过，#212，test_k12_ipc_caps）；真机发射留登记 （C/SRF 串联提取对拍+渲染零厚 vs CALC 侧壁 t_um 差异注记待真机批， 本批零发射）
- 失败模式坑账链（playbook 命中 17 条，坑号 #NNN 为 开发注记 出处标记）：
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
