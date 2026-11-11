# 能力卡：layered_stack

> 由 scripts/capability_cards_export.py 离线生成（确定性输出）；数据源与坑号链见文中逐条标注。

## 适用场景

- 拓扑：晶圆键合叠层+空腔（外部用户实测反馈 §3.4/§2.1 锚，aurora_q 批 1 91ef1a1c 落渲染、批 2 注册）：五层叠层 silicon/gold/silicon/gold/ silicon=0.25/0.003/0.05/0.003/0.25mm（族常量，§3.4 示例）、矩形腔 （0.9×0.5×5.1mm）贯通线长且关于带面对称（分层围合零布尔，腔足印内 非导体层挖除、导体层完整横跨=膜悬置键合族定义性质）、腔壁金属化四壁 零厚 PEC（两端截面口不金属化=端口见腔截面，3µm 涂层 RF 等效）、载带= 导体层顶面零厚 PEC 片悬置于腔内、双 StripLinePort（prop_dir=x/ exc_dir=z，height=带面-腔顶壁）落腔端截面=模型端面；§2.2 真空约定= 普通盒完全包住（不布尔差直接重叠）
- f0：95.0 GHz ｜ 端口：2 ｜ 时长 ≤30.0 ns ｜ 网格档：0.0 mm
- 提取口径：S11/S21 @ StripLinePort 1-2（腔端截面波端口，suspended_stripline/sicl 同法；β 金标准→εeff 对照闭式锚 |Δ|≤2% 口径同 stripline 族；|S11| 带谷= Z0 锚（ref=50，闭式 Z0 偏差见渲染 meta closed_form 注）；port_beta.csv 8 列契约=SSL/sicl 逐字节同）
- 参数：strip_w_mm, line_len_mm, wafer_width_mm, cavity_w_mm, cavity_h_mm
- 基板：{"er":11.9,"h_mm":0.05,"tan_d":0.0}

## 名义参数

| 参数 | 名义值 |
|---|---|
| cavity_h_mm | 0.5 |
| cavity_w_mm | 0.9 |
| line_len_mm | 5.1 |
| strip_w_mm | 0.5243362925046158 |
| wafer_width_mm | 1.2 |
- 名义参数来源：`docs/templates/layered_stack/meta.yaml`（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）

## 敏感性排序（R9 先承诺）

- 出处=computed（幅值分数登记表 `knowledge/sensitivity_rankings.yaml`；证据 scripts/sensitivity_rankings_build.py；坏条目拒收如实降级 #105）

- 方法 central_finite_difference_elasticity ｜ n=11 ｜ 证据：scripts/sensitivity_rankings_build.py

| rank | 参数 | 分数 |
|---|---|---|
| 1 | cavity_h_mm | 0.73949 |
| 2 | strip_w_mm | 0.604546 |
| 3 | cavity_w_mm | 0.0 |
| 4 | line_len_mm | 0.0 |
| 5 | wafer_width_mm | 0.0 |
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

- 参数语义：strip_w_mm=载带宽（Z0 由悬置闭式反解单源 design_params：50Ω@b=0.50/ h=0.05/εr=11.9 → w=0.5243362925046158，正向复算自洽 |ΔZ0|≤1e-9Ω； HFSS 反馈 §2.1 实测 w=0.52→Z0≈50.2 经验锚背书，|S11|max=-23.5dB）， line_len_mm=腔管/线长（§2.1 实测锚 5.1）， wafer_width_mm=叠层横向总宽（§5 实测锚 1.2），cavity_w_mm=腔宽（须 >带宽 且 <wafer 宽——spec 校验器守卫），cavity_h_mm=腔高（腔关于带面 对称=spec 校验器唯一合法形态，z0=-h/2 派生；§3.4 示例 0.5）。layers 叠层=族常量不入参数表（元组列表不适配 audit 布线机制；金属层作走线 层留后续批）
- 网格：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50@F_MAX（最高 εr 介质 silicon 11.9，SIW/sicl 同口径；95GHz 档 BASE≈18.2µm）；特征线 显式入网（带面/膜面/腔壁面/带缘/壁缘/晶圆缘）+ 次胞界面剔除（#349 地板 10µm：3µm 键合层界面不入网）+ NEAR≤带宽/3 守卫（#266）+ 全轴 1µm 近重合去重与落格断言（#152/#283）
- 冒烟现状：未冒烟（离线审计过，#212，test_template_geometry_audit 全门+ test_layered_stack_audit 批 1 审计）；真机发射留后续批（β/εeff 对照 闭式锚判读+跨引擎 HFSS 仲裁=批 2 锚判读口径，见 render_layered_stack 模块头判定注记）
- 失败模式坑账链（playbook 命中 17 条，坑号 #NNN 为 DEVLOG 出处标记）：
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
