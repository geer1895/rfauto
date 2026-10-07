# 能力卡：helix

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：螺旋（§10.3 C1）：单导线 staircase 方螺旋（每圈 4 直段各 1/4 螺距上升 + 角部竖板，无双并联回路），首圈 A 段即馈口顶，总线长 4·d·N + N·p = k_helix·λ0/4（k_helix=1.3615 HFSS 仲裁）；馈口=地面 z=0 → 角 A 柱底 LumpedPort；无介质板（PEC 地面悬空导体）
- f0：2.4 GHz ｜ 端口：1 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11 @ LumpedPort 1（法向模方螺旋：判据=Zin 电抗容→感上穿 f_x，R 电小失配谷深不适用；旧 λ0/4 口径真机 f_x 3.31GHz，HFSS 同几何仲裁 3.2675GHz 偏差 1.44% AGREE → k_helix=1.3615 定版，见 smoke_note）
- 参数：helix_d_mm, helix_turns, helix_pitch_mm, helix_w_mm, feed_gap_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| feed_gap_mm | 2.0 |
| helix_d_mm | 3.0 |
| helix_pitch_mm | 9.2587 |
| helix_turns | 2 |
| helix_w_mm | 0.6 |
- 名义参数来源：`docs/templates/helix/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=11 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | helix_turns | 1.0 |
| 2 | helix_d_mm | 0.564462 |
| 3 | helix_pitch_mm | 0.435513 |
| 4 | feed_gap_mm | 0.0 |
| 5 | helix_w_mm | 0.0 |
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

- 参数语义：helix_d_mm=方截面中心线边 d，helix_turns=圈数 N（整数，int() 截断），helix_pitch_mm=螺距 p（=(k_helix·λ0/4−4dN)/N 反解，守卫 ≥1mm），helix_w_mm=导带宽，feed_gap_mm=馈口高
- 网格：辐射器件：上方/侧向空气隙 λ0/4；z 网格专项（各圈 1/4 螺距面全部入网，_ANTENNA2_TALL_TEMPLATES）
- 冒烟现状：真机 runs/antenna2_smoke/helix（2026-09-14）FAIL：S11 ≤−1.22dB；Zin 全带容性 X∈[−156,−44]Ω 且随 f 单调升 → 谐振在 2.9GHz 之上（与段首"慢波使谐振更低"预期相反，λ0/4 总线长口径高估电长度）；R=1.8~6.2Ω 与电小天线 395(h/λ)²≈2Ω 一致——即便谐振也对 50Ω 失配，S11 谷深判据不适用，应改判电抗过零。扩带（2026-09-16，runs/antenna2_smoke/helix_wide，1.5-4.5GHz，solve 173s）FOUND：f_x=3.3146GHz R=9.47Ω（首个容性→感性上穿）。**HFSS 同几何仲裁（2026-09-17 收尾批，scripts/hfss_helix_arbitration.py，runs/helix_arbitration）AGREE**：真实三维盒几何（t*_d 段为 0.6×3.0×0.9 金属块，前六轮 sheet 映射把它压成薄板断了 C→D→A 电流路径 → 全带容性 UNDECIDABLE，几何修复后）f_x_hfss=3.2675GHz R=8.74Ω vs openEMS 3.3146（自动/0.35mm 网格、16.7/50mm 域三重稳健 3.29–3.32）偏差 1.44% ≤5% ⇒ k_helix=f_x(HFSS)/2.4=1.3615 进设计式（K_HELIX 单源），helix_pitch_mm 3.6142→9.2587（element_top 9.23→20.52mm）；新名义真机验证 runs/antenna2_smoke/helix_knew（openEMS 1.9–2.9GHz）FOUND f_x=2.2039GHz R=17.51Ω、S11 min −6.74dB@2.275——落 f0±12% 窗内但偏低 −8.2%：单点 k 修正隐含 f∝1/wire，螺距 3.6→9.3mm 改变慢波因子致一阶外推过冲；割线二次迭代（两点 (31.23mm,3.3146)/(42.52mm,2.2039) → wire≈40.5mm、k≈1.30、pitch≈8.26）须再经 HFSS 仲裁方可进设计式（#190，followUp）。
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
