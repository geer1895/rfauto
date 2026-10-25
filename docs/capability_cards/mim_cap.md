# 能力卡：mim_cap

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：GaAs IPD MIM 电容：下极板（零厚金属面 z=H，上极板足迹外扩 bot_overhang）- 介质薄层（真实体块 z∈[H,H+d]，SiNx）- 上极板（零厚 金属面 z=H+d，W×L 叠合面积=C 的 A）；竖直 LumpedPort 跨介质（上-下 极板之间，exc 沿 z，并联形式）；全域 MUR（电小器件近场主导）； stackup z 叠算+共形介质单足迹退化档消费（render 模块头）
- f0：2.0 GHz ｜ 端口：1 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ LumpedPort 1（上极板-下极板竖直跨介质，R=50Ω CalcPort 同参考； Zin=50(1+S11)/(1−S11)→低频段 C=−1/(ω·Im(Zin)) 提取，Im(Zin) 过零= 串联 SRF 判读——并联形式，Zin=R_s+jωL_s+1/(jωC)；C±25%/SRF>2×f0 质量判据由 CALC 键 mim_capacitance 承载）
- 参数：w_um, l_um, d_um, bot_overhang_um, port_um, h_mm, er_diel, tand_diel
- 基板：{"er":12.9,"h_mm":0.1,"tan_d":0.0006}

## 名义参数

| 参数 | 名义值 |
|---|---|
| bot_overhang_um | 5.0 |
| d_um | 0.2 |
| er | 12.9 |
| er_diel | 7.5 |
| h_mm | 0.1 |
| l_um | 20.0 |
| port_um | 2.5 |
| tan_d | 0.0006 |
| tand_diel | 0.001 |
| w_um | 20.0 |
- 名义参数来源：`docs/templates/mim_cap/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=21 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | d_um | 1.0 |
| 2 | er_diel | 1.0 |
| 3 | l_um | 1.0 |
| 4 | w_um | 1.0 |
| 5 | bot_overhang_um | 0.0 |
| 6 | er | 0.0 |
| 7 | h_mm | 0.0 |
| 8 | port_um | 0.0 |
| 9 | tan_d | 0.0 |
| 10 | tand_diel | 0.0 |
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

- 参数语义：w_um/l_um=上极板叠合区宽/长（μm，C 的 A=w·l），d_um=介质厚（μm， SiNx 0.2μm 典型档），bot_overhang_um=下极板四周外伸（μm，抑制边缘场 集中），port_um=端口盒 x/y 跨距（μm，≥2 格 #283），h_mm=基板厚 （仓内基板惯例 mm，GaAs 100μm 档）；er_diel/tand_diel=介质 εr/损耗 （SiNx）；er/tan_d 走 substrate/nominal（GaAs）——W/L/D 全 μm 为 IPD 工艺口径，经 core.stackup.to_mm(v,'um') 单源换算（μm 帮手函数）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 max(port,d)（μm 尺度 几何驱动网格——base 取最细 x/y 特征端口盒，#266 守卫 NEAR=base/4 ≤ port/3；禁 λ_sub/50 口径）；极板缘/端口盒边+中线精确入网（#198）； 介质薄层 z 向三线（H、H+d/2、H+d）显式入网——端口激励体积 ≥2 格 （#283），#152 去重阈值 z 轴降为 d/4（全局 1µm 阈值吞介质线——薄层 适配）；min z-cell=d/2 → dt≈d/2c（薄介质 FDTD 物理成本，真机预算留 登记）
- 冒烟现状：未冒烟（离线审计过，#212，test_k12_ipc_caps）；真机发射留登记 （C/SRF 低频回收对拍待真机批，本批零发射）
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
