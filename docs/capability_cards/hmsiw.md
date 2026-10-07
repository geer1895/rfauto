# 能力卡：hmsiw

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：HM-SIW 半模基片集成波导均匀段（TA-8）：基板矩形域，底板=显式零厚板贴 z=0 PEC 底界+单列过孔藩篱 x=+w/2（藩篱止于端口面），开路边 x=−w/2=磁壁（域 MUR 余量 w_eff/2）、顶开放（MUR，无上板——HMSIW 定义性质）；端口=两端面 LumpedPort z 桥（跨介质孔径、R=Z_PV， 端口即终端负载 siw v2 口径）——准 TE0.5 模 fc 由式 (11) 链给出（Lai-Fumeaux 2009 T-MTT 式 (8)-(14)）
- f0：10.0 GHz ｜ 端口：2 ｜ 时长 ≤45.0 ns ｜ 网格档：0.0 mm
- 提取口径：LumpedPort z 桥×2 端面口径（R=闭式 Z_PV=2h·Z_TE/w_eff，CalcPort 同参考）： β/εeff 主判=S21 解缠相位斜率÷port_beta.csv 实测 plane_dist（cps/siw 同契约，LumpedPort 无 β 属性）；fc 由带内 φ(f)=−β(f；fc)·L+φ0 单参数拟合对照式 (11) 链（预声明门归真机窗）
- 参数：w_mm, d_mm, s_mm, line_len_mm
- 基板：{"er":3.66,"h_mm":0.508}

## 名义参数

| 参数 | 名义值 |
|---|---|
| d_mm | 0.6 |
| er | 3.66 |
| h_mm | 0.508 |
| line_len_mm | 63.0721 |
| s_mm | 1.0 |
| tan_d | 0.0037 |
| w_mm | 5.5829 |
- 名义参数来源：`docs/templates/hmsiw/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑导出器自动上卡，不硬凑）

## 判据

- 锚覆盖 5：coupled_microstrip.kj_even_domain.lit-v1、cps.gamma_er.fdref-v1、hmsiw.fc_ghz.closedform-v1、mmt.inductive_post_b.hfss-v1、mmt.resonant_window_fres.hfss-v1（core/anchors；通配 + 专属）
- 健康门：无模板作用域专属健康门（gate 如实不判，#274 口径）
- 通用体检：求解健康度体检 G11 九因子（core/solve_health；service/health_service.health_check_run 按 run 装载产物判定）

## 引擎精度卡（跨引擎仲裁锚）

- `coupled_microstrip.kj_even_domain.lit-v1`（constant/active；闭式/文献锚（无引擎对））：kj_even_domain_dev_pct = 0.66 percent；±1.0（arbitration_interval）；verdict KJ_VINDICATED_J1_PASS（Elmer 三紧缝/域缘点 even −0.180%/−0.590%/−0.439% 全 J1 PASS；p2_summary.json overall=FAIL 属 HFSS 测量面非 KJ 本体，勿混淆）；证据：runs/df7_kjeven
- `cps.gamma_er.fdref-v1`（formula/active；闭式/文献锚（无引擎对））：cps_gamma_er expr = 1 + 0.9014*er**-0.6361（变量：er）；±0.006（relative）；证据：runs/df6_dp14m1、runs/df6_dp18c9
- `hmsiw.fc_ghz.closedform-v1`（constant/experimental；引擎对 closedform（None 仲裁））：hmsiw_fc_te05_ghz = 6.666664 GHz；±0.0001（rounding_band）；证据：runs/ge8_followup/wave_a/refs
- `mmt.inductive_post_b.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：inductive_post_b_dev_pct = 9.224 percent；±7.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- `mmt.resonant_window_fres.hfss-v1`（constant/active；引擎对 mmt（hfss 仲裁））：resonant_window_f_res_dev_pct = 16.6 percent；±3.0（arbitration_interval）；verdict AGREE_HFSS；证据：runs/mmt_anchor_20260930
- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，status/版本演进口径见该文件头注；本节零计算零求值）

## 已知边界

- 参数语义：w_mm=HMSIW 宽（过孔列心到开路边；设计链 core/hmsiw.hmsiw_design_params：fc 目标=f0/1.5 反解，式 (8)(9)(13)(10)(11) 联立 brentq，名义 5.5829mm@fc=6.6667GHz/er=3.66/h=0.508/d=0.6/s=1.0）、d_mm=过孔直径、 s_mm=过孔心距（渲染按 k·s 精确栅格、藩篱止于端口面）、line_len_mm=两端口测量面间距； h/er/tan_d 走 substrate/nominal（式 (13) 声明域 εr∈(2.2,15)/h∈(0.254,2.54)mm/w∈(2.5,10)mm， hmsiw_check_validity 越界拒渲染）
- 网格：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线（siw 同款）、显式近场线 10µm 地板（#349）、端口盒边/开路边/藩篱心线落格（#283， 生成期断言）、基板 z 4 层
- 冒烟现状：离线审计先行（#212，test_ta_wave_a_templates）；内核数字裁判=论文图面数值锚三方互证（Fig.6/7：fc 4.789/20.746GHz、β(12GHz) 342 rad/m，test_ta_wave_a_templates 钉）；近似级别如实登记：式 (13) 拟合 <2%（论文声明域内）、过孔藩篱离散化未经真机仲裁（siw 经验迁移）、端面 LumpedPort R=Z_PV 对 1/4 余弦场分布的功率-电压近似（siw v1/v2 同族近似级）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
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
