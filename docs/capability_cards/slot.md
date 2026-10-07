# 能力卡：slot

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：缝隙（§10.3 C1）：z=0 有限金属地（4 盒拼合、槽 L×Ws 留空）+ z=h 50Ω 微带馈线 y 向垂直跨槽居中 + 双 MSLPort 板边端接（y=∓BOARD，单轴 PML）；底 MUR + z 向下延 λ0/4（槽向下半空间也辐射，PEC 底会短路槽）
- f0：2.4 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ MSLPort 1-2（地面谐振缝：S21 辐射凹位置+深度=谐振判据，过缝辐射负载使 S11 全带平坦不适用；真机 −16.41dB@2.665GHz PASS；判读窗收内带 f0±0.4GHz + Σ|S|²>1.02 点剔除——带边 Σ|S|²>1 为高斯激励 −20dB 带边归一化伪象，见 smoke_note）
- 参数：slot_l_mm, slot_w_mm, feed_w_mm, feed_margin_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| feed_margin_mm | 12.0 |
| feed_w_mm | 1.1134 |
| slot_l_mm | 40.9168 |
| slot_w_mm | 2.0 |
- 名义参数来源：`docs/templates/slot/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=9 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | slot_l_mm | 1.0 |
| 2 | feed_margin_mm | 0.0 |
| 3 | feed_w_mm | 0.0 |
| 4 | slot_w_mm | 0.0 |
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

- 参数语义：slot_l_mm=缝长（λ0/(2√((1+εr)/2))，Booker 对偶+半空间均值口径），slot_w_mm=缝宽，feed_w_mm=馈线宽（50Ω HJ），feed_margin_mm=板边到馈线手画段起点的馈段长（MSLPort 自画，MeasPlaneShift=margin/3）
- 网格：辐射器件：上方/侧向/下方空气隙 λ0/4；地缘/槽缘/馈线缘精确入网
- 冒烟现状：真机 runs/antenna2_smoke/slot 与 slot_override（2026-09-14）PASS×2：S21 辐射凹 −16.41dB @2.665GHz（L=40.9168，+11.0%，隐含 εeff 1.84）/ −21.76dB @2.6275GHz（L=46.036，隐含 εeff 1.54）；k_slot∈[0.66,0.79]·(1+εr)/2 待 HFSS 仲裁后才进设计式（#190）。Σ|S|² 带边 >1 已排查（2026-09-16，slot/sparams.csv 实测）：1.9GHz=1.212、2.9GHz=1.128，>1.02 的点全部落在 1.9-2.08 与 2.82-2.9 两侧，f0±12% 判读窗（2.112-2.688GHz）内 ≤1.008——越限恰在 SetGaussExcite(F0,FC) 高斯激励 −20dB 带边（评估带=激励带，uf_inc 归一化分母趋零放大数值噪声），归一化伪象而非 MSLPort/有限地物理错；判读口径=窗收内带 f0±0.4GHz（激励带内 80%）+ Σ|S|²>1.02 点剔除（scripts/smoke_antenna2_anchor.py 全模板通用；掩模后 307/321 点，凹位/深度不变），全局 FC 不动（f_max 进网格预算，改激励带会漂全部模板网格锚）
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
