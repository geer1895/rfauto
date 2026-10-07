# 能力卡：loop

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：环形（§10.3 C1，2026-09-16 自由空间改造）：z=0 方环（中心线边 a、带宽 w，顶/左/右全跨含角）+ 底边中央断口 g（馈口位）LumpedPort 跨断口（E 沿 x，dipole 中央馈口同型）；无基板无地：底 MUR + 域 z 向下延 λ0/4（dipole 同款）
- f0：2.4 GHz ｜ 端口：1 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ LumpedPort 1（一周长方环，自由空间口径：判据=Zin 电抗过零 f0±12% + 过零处 R≥20Ω，S11 −5dB 次级；旧贴地口径真机 R=0.56Ω 镜像抵消 FAIL，v2 见 smoke_note）
- 参数：loop_side_mm, loop_w_mm, loop_gap_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| loop_gap_mm | 1.0 |
| loop_side_mm | 31.2284 |
| loop_w_mm | 1.0 |
- 名义参数来源：`docs/templates/loop/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=7 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | loop_side_mm | 1.0 |
| 2 | loop_gap_mm | 0.0 |
| 3 | loop_w_mm | 0.0 |
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

- 参数语义：loop_side_mm=方环中心线边 a（一周长 C=4a≈λ0，自由空间 a=λ0/4，εeff→1），loop_w_mm=环带宽，loop_gap_mm=底边断口宽（<a，激励向 x 跨度）
- 网格：辐射器件：上方/侧向/下方空气隙 λ0/4；环带缘/断口缘精确入网
- 冒烟现状：真机 v1 runs/antenna2_smoke/loop（2026-09-14，旧贴地口径 λg/4=18.5515、z=h 贴 PEC 地）FAIL：S11 −0.19dB；Zin 电抗过零 2.3825GHz（−0.7%，谐振长度口径正确）但 R=0.56Ω。归因（像理论，v2 实证）：水平环贴 PEC 地 0.508mm（0.004λ0），镜像反向电流抵消辐射 → R_rad→0。改造（2026-09-16）：自由空间口径（无板无地、底 MUR、域下延 λ0/4、环面 z=0、a=λ0/4=31.2284），判据改电抗过零 f0±12% + 过零处 R≥20Ω（S11 −5dB 次级；一周长环馈阻抗文献 ≈100-200Ω 对 50Ω 固有失配，谷深非谐振判据）。v2 真机 runs/antenna2_smoke/loop_v2（2026-09-16，solve 352s）PASS：Zin 电抗过零 2.6774GHz（+11.6%，端效应窗内）R=112.02Ω（v1 0.56Ω → 112Ω，镜像抵消归因实证；落在文献 100-200Ω 带内），S11 −8.67dB@2.64GHz（次级 −5dB 门过）；判读窗 2.0-2.8GHz 321/321 点全保留（Σ|S|² 全带 ≤0.94，无带边伪象）；谐振位 +11.6% 为细带/断口馈电端效应，设计式不预补偿（#190）
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
