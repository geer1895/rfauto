# 实测对齐链路：从 Touchstone 到参数提案

> 把"实测 VNA 数据 ↔ 仿真对齐、偏差诊断、修正提案"串成一条命令链
> （SO 走查任务 B 的 B5 断点收口）。全部命令离线可跑（实测文件在手时），
> 真机采集另见 `rfauto vna measure`（需仪器）。

## 链路总览

```
实测 .s2p ──► correlate（FSV/GDM 相关性）
        ├──► vna en-report（GUM 不确定度预算）
        ├──► diagnose deviation（偏差归因桥：FSV/相关性 → 四段式侦探叙事）
        ├──► diagnose cm / q（物理量反提：耦合矩阵 / Q 双通道）
        └──► agent propose（偏差定向参数提案，三层 Gate）──► agent apply
```

## 1. 相关性对拍（FSV/GDM 四级评定）

```bash
rfauto correlate sim.s2p meas.s2p --threshold 3.0
```

不相关时退出码 1，`metrics` 给出逐迹线最大/平均 dB 偏差。FSV 六级
短码（Ex/VG/G/F/P/VP，IEEE 1597.1 口径）在下一步的偏差归因桥里
逐迹线展开。

## 2. 偏差归因桥（实测残差 → 侦探叙事）

```bash
rfauto diagnose deviation sim.s2p meas.s2p --run-dir runs/<id> --json
rfauto diagnose deviation sim.s2p meas.s2p --en --markdown report.md
```

- 输入：仿真/实测两个 Touchstone；`--run-dir` 只作 provenance 指针。
- 输出四段式：发现（FSV 逐迹线指纹）→ 根因假设（实测链暂无 playbook
  规则，如实为空）→ 证据链（取证命令）→ 结论（确定性模板叙述，
  数字全部入白名单可审计）。
- `--en` 附 En 不确定度报告（GUM 预算缺省模板；换表见
  `configs/uncertainty_budgets.yaml`）。

边界（诚实面）：偏差**数字**只来自确定性内核（correlate/FSV/En）；
桥不从偏差数字臆造参数值——参数提案必须显式给值（下一步）。

## 3. 物理量反提（滤波器族）

```bash
rfauto diagnose cm meas.s2p --f0 2.5 --fbw 0.1 --target target_cm.json
rfauto diagnose q  cavity.s1p --f0 2.5 --qe 250
rfauto diagnose cat step1.s2p --f0 2.5 --fbw 0.1 --target target_cm.json
```

`cm` 反提耦合矩阵对照设计目标（逐元素偏差表）；`q` 双通道互证
（VF 极点法 × Kajfez 圆拟合，|ΔQu|/Qu≤10% 才 AGREE）；`cat` 是
Dishal 顺序调谐 critique（τ 峰数指纹 + typed fixes）。

## 4. 参数提案（三层 Gate，只 propose 不 apply）

```bash
rfauto agent propose recipes/my_bpf.yaml --params '{"gap_mm": 0.45}'
rfauto agent apply recipes/my_bpf.yaml --token <token> --params '{"gap_mm": 0.45}'
```

- `--params` 的值由你（或上一步 typed fixes/设计经验）显式给出；
  提案过 L1 白名单 + L2 dry-run 两道门，返回 L3 确认 token。
- 对仿真 run 的 metrics 诊断，还可用
  `rfauto agent propose <recipe> --from-diagnosis <run_id>` 直接从
  run 诊断段取 initial_values（仿真链口径；实测链走 `--params`）。
- token 是 L1/L2 结果的派生哈希——apply 时参数被篡改会被拒。

## 5. 重仿真与回放

```bash
rfauto run recipes/my_bpf.yaml -a openems
rfauto vna-replay meas.s2p --sim new_sim.s2p     # 离线回放全链
rfauto warm-start <study> --dataset <数据集>       # 历史数据先验注入
```

## 下一步

- 采集与校准：`rfauto vna measure --help`（真机）、
  `rfauto vna calibrate --help`（独立校准/去嵌入口）
- 判读纪律（先验证模型再校准）： 规则 1b；
  `docs/how-to/read-verdict-gates.md`
- 偏差深查（仿真侧指纹）：`rfauto diagnose detective --run-dir runs/<id>`
