<!-- PR-10 文档站同步副本：源=docs/tutorials/circuit_diagrams_and_reports.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 电路图、ADS 前仿调参回路与设计回放报告

> 三个面一条线：**画图**（电路图四叶：链路框图/测试连接图/评审标注/PCB
> 叠层，输出原生可编辑 `.drawio`，图上数字来自确定性内核或你的原值）→
> **调参**（ADS 前仿回路：出参数化电路图 → 你在 draw.io 里改值 → 网表 →
> hpeesofsim → 指标反标注回图 → 再改）→ **总结**（设计回放报告：把一次
> 优化 run 的轨迹、最终设计、verdict 门表与电路图入口收成一份 md）。
> 本文命令均在开发环境实测：生成器叶按原样真跑（确定性纯函数）；需要
> ADS 的 `ads-circuit run` 只在无 ADS 隔离环境做 dry 演示，真机数字取自
> 仓内真机冒烟档案（输入与本文步骤产物逐字节一致，见 §2）；输出为实测
> 摘录。前置：`docs/tutorials/getting-started.md`（CLI 入门）、
> `docs/tutorials/first_optimization_loop.md`（§3 需要一个优化 run）。
> 英文版（English version）：`docs/tutorials/circuit_diagrams_and_reports_en.md`。

## 0. 先看全貌：三个面各管什么

| 面 | 入口 | 你给什么 | 你得到什么 | 图/报告上的数字从哪来 |
|---|---|---|---|---|
| 电路图四叶 | `rfauto diagram link/testsetup/annotate/stackup` | 级表 / 测试场景 / 标注表 / 叠层（JSON） | 原生可编辑 `.drawio` | link=Friis 级联内核；stackup 线宽=综合内核；其余=你的原值原样标注（零换算） |
| ADS 前仿回路 | `rfauto ads-circuit diagram/run/annotate` | 模板族 + Touchstone（`.sNp`） | 参数化电路图 → 网表 → 指标反标注图 | 网表=确定性渲染器；指标=系统指标内核；求解=ADS hpeesofsim |
| 设计回放报告 | `rfauto design-report <run_id>` | 一个 run（runs/ 下目录名或路径） | 六节 md 报告 | 每个数字带来源标注（湖文件键 / 派生公式 / 服务函数） |

三个面共用的几条纪律，读图读报告时心里有数：

- **原生可编辑**：产物是未压缩的 mxGraph XML，draw.io 桌面版或 VS Code
  的 Draw.io Integration 插件直接打开、拖动、改字；不是截图。
- **确定性**：同输入两次运行，输出文件逐字节相同（零时间戳零随机 id；
  设计报告唯一豁免是"生成时间"那一行）。所以 `.drawio` 适合进版本库做
  diff。
- **数字不手抄**：图上的计算数字只出自确定性内核；声明式输入（损耗、
  长度、意见文本、叠层厚度）原值原样上图，生成器不做任何 dB 运算。
- **写面纪律**：原稿只读。`--out` 的父目录必须已存在；反标注/评审产物
  禁止覆盖原稿（同路径显式报错）。
- **信封**：每叶都有 `--json`，成功和失败同构（`ok`/`errors`），脚本和
  工作流直接消费；人读模式适合交互。

## 0.1 准备工作目录，以及怎么在 draw.io 里核对

本文所有命令在仓根执行（Git Bash）。先建一个输出目录（`runs/` 在
`.gitignore` 里，产物不会弄脏 `git status`）：

```bash
mkdir -p runs/tutorial_diagrams
```

仓内备有可直接打开的样例（每个都能用 §1 的命令逐字节复现）：

| 样例 | 由哪叶生成 | 输入文件（同目录） |
|---|---|---|
| `examples/diagrams/rf_link_diagram_example.drawio` | `diagram link` | `rf_link_chain_example.json` |
| `examples/diagrams/testsetup_vna_two_port_example.drawio` | `diagram testsetup` | `testsetup_vna_two_port_example.json` |
| `examples/diagrams/review_annotated_example.drawio` | `diagram annotate` | 底图=`rf_link_diagram_example.drawio`，标注=`review_annotations_example.json` |
| `examples/diagrams/stackup_microstrip_example.drawio` | `diagram stackup` | `stackup_microstrip_example.json` |

手动核对的方法：draw.io 打开样例 → 看图元位置与文字 → 选中任意元件按
右键 **Edit Data…**（快捷键 Ctrl+M）看自定义属性 → **Extras > Edit
Diagram** 可看原始 XML。保存时保持 **File > Properties > Compressed 不勾**
（draw.io 对新文件缺省就不压缩；rfauto 的读回端只认未压缩页，压缩页会
被显式拒绝，§2 的人工调参环节尤其要注意）。

## 1. 电路图四叶（`rfauto diagram`）

### 1.1 link：链路框图（Friis 级联，算画同源）

输入是"级表"：一个 JSON 数组，顺序即信号流向，每级严格三键
`name/gain_db/nf_db`：

```bash
cat examples/diagrams/rf_link_chain_example.json
rfauto diagram link --chain-file examples/diagrams/rf_link_chain_example.json \
  --title "接收前端链路框图（rfauto diagram link 示例——数字=内核 Friis 单源）" \
  --out runs/tutorial_diagrams/link.drawio --json
```

不带 `--json` 时的人读输出（实测）：

```
RF 链路框图  4 级  级联 ΣG=41.00 dB  ΣNF=1.37 dB（Friis，内核单源）
  #1 LNA  G=20.00 dB  NF=0.80 dB  ΣG=20.00 dB  ΣNF=0.80 dB
  #2 镜像抑制滤波器  G=-2.00 dB  NF=2.00 dB  ΣG=18.00 dB  ΣNF=0.82 dB
  #3 混频器  G=-7.00 dB  NF=7.00 dB  ΣG=11.00 dB  ΣNF=1.04 dB
  #4 中频放大器  G=30.00 dB  NF=3.50 dB  ΣG=41.00 dB  ΣNF=1.37 dB
✓ 已写出 runs\tutorial_diagrams\link.drawio（draw.io/VS Code Draw.io 插件可打开编辑）
```

图上每个框标"本级 G/NF + 到该级为止的级联 ΣG/ΣNF"，链尾一个绿色总计
框。ΣNF 一栏就是 Friis 公式的逐级累计——读法：混频器那级 ΣNF 从
0.82 dB 跳到 1.04 dB，说明噪声预算主要花在这里（§1.3 的评审样例正是
圈的这一级）。上面带 `--title` 的命令产物与
`examples/diagrams/rf_link_diagram_example.drawio` **逐字节相同**（实测
`cmp` 零差异）。级表也可以内联给：`--chain '[{"name":"LNA","gain_db":20,"nf_db":0.8}]'`
（`--chain` 与 `--chain-file` 恰给一）。

### 1.2 testsetup：测试连接图（声明式，零换算）

输入是一个场景对象，顶层四键 `title/instruments/connections/notes`：

- 仪器卡严格六键 `id/kind/label/role/ports/note`（前四必填）。`kind` 是
  固定枚举：`vna`、`siggen`、`specan`、`powermeter`、`dut`、`lisn`、
  `attenuator`、`coupler`、`amplifier`、`generic`——它决定缺省角色与配色，
  角色再决定布局列（激励 → 串入件 → DUT → 分析仪 → 辅助）；未知 kind
  显式报错，不静默兜底。
- 连接边严格五键 `from/to/cable/cal_plane/label`，端点写成
  `<仪器 id>.<端口名>`；引用未声明的端口直接报错（拓扑正确性是第一验收面）。
- `cable` 三键 `label/loss_db/length_m`，图上原样拼成
  `C1  0.5 dB  1 m`；`cal_plane: true` 的边挂红色 `▎CAL` 校准面标记。
- 注记两键 `text/anchor`，`anchor` 可指向 `conn0` 这样的连接 id。

```bash
rfauto diagram testsetup \
  --scene-file examples/diagrams/testsetup_vna_two_port_example.json \
  --out runs/tutorial_diagrams/testsetup.drawio --json
```

人读输出（实测）：

```
测试连接图  仪器 2 台  连接 2 条  注记 1 条（声明式场景，标注零换算）
```

更复杂的例子（信号源 + LISN + EUT + 频谱仪的传导发射布置）见
`runs/aurora_o/tn_o6/samples/cispr_conducted.json` 与同名 `.drawio`。

### 1.3 annotate：评审标注双层（底图锁定 + 标注层）

评审时你要的是"在原图上圈问题、写意见，但别碰原图"。annotate 把底图放
进锁定层、标注放进独立的 `annot` 层：

- **形态 A**：`--source` 给 `.drawio`，底图层整层 `locked`（draw.io 里
  拖不动被审图元）；
- **形态 B**：`--source` 给 `.png/.jpg` 截图，底图 cell 用样式锁定；
  图片头解析不出尺寸时用 `--image-size 1280x720` 兜底。

标注 JSON 顶层 `summary + annotations`，每条严格六键
`id/region/priority/label/comment/target`：`region` 是圈的位置
`{x,y,w,h}`，`priority` 映射三色（`high`=红、`medium`=橙、`low`=绿），
`target` 写底图里被审元素的 id（如 `stage2`），生成一条指示虚线——id
写错会显式报错。

```bash
rfauto diagram annotate \
  --source examples/diagrams/rf_link_diagram_example.drawio \
  --annotations @examples/diagrams/review_annotations_example.json \
  --reviewer "RF 评审组" \
  --out runs/tutorial_diagrams/review.drawio --json
```

人读输出（实测）：

```
评审标注图  形态 A  标注 3 条  target 指示边 3 条（底图锁定 base_locked=True，标注层 annot）
```

`--out` 与 `--source` 同路径会被拒绝（实测
`source 与 out_path 同路径（…）：评审原稿不可覆盖，请另给输出路径`）。
形态 A/B 的另一组样例：`runs/aurora_o/tn_o8/annotated_form_A_sample.drawio`、
`annotated_form_B_sample.drawio`。在 draw.io 里打开后，Layers 面板能看到
"底图（评审锁定）"与"评审标注"两层——要改底图先在面板里解锁。

### 1.4 stackup：PCB 叠层横截面（线宽走综合内核）

叠层 JSON 顶层 `title/layers/width_annotations`：层卡自顶向下，严格五键
`name/kind/thickness_mm/material/er`，`kind` 只能是
`signal/plane/dielectric`；`width_annotations` 是你手头已知的线宽
（`layer/width_mm/note`，原值标注）。如果线宽要"算出来"而不是"抄进来"，
用 `--width-synth`：给目标阻抗、频率和 `configs/materials.yaml` 里的层叠键，
线宽由 `core/synthesis.nominal_width_mm` 单源算出后逐位上图。

```bash
rfauto diagram stackup \
  --stackup-file examples/diagrams/stackup_microstrip_example.json \
  --width-synth '{"layer": "TOP", "z0_ohm": 50, "freq_ghz": 2.5, "stackup_name": "rogers4350b_h0.508"}' \
  --out runs/tutorial_diagrams/stackup.drawio --json
```

人读输出（实测）：

```
PCB 叠层图  3 层  线宽标注 1 条（层带高度∝厚度；标注=输入原值/合成单源）
  #0 TOP [signal]  0.035 mm  zmin=0.0 mm
  #1 SUB [dielectric]  0.508 mm  εr 3.66  zmin=0.035 mm
  #2 GND [plane]  0.035 mm  zmin=0.543 mm
  线宽 TOP: 1.1134 mm（synthesis.nominal_width_mm）
```

层带高度按同一比例尺正比于厚度（过薄的层会在 warnings 里提示），
`zmin` 是自顶向下的累计深度；线宽标注括号里写明来源，`--json` 信封的
`width_annotations[].synthesis` 回显综合参数。六层板的样例：
`runs/aurora_o/tn_o3/sample_6layer_SGSPGS.drawio`。

> Windows 提示：`--width-synth` 只收内联 JSON。Git Bash 的单引号原样传参；
> 旧版 PowerShell 给原生命令传参会剥掉内嵌双引号，内联 JSON 请在 Git
> Bash 里跑。其余几叶都有文件形态（`--chain-file`/`--scene-file`/
> `--stackup-file`、`--annotations @文件`）。

### 1.5 在 draw.io 里手动核对（建议每次出新图都过一遍）

| 图 | 打开后看什么 |
|---|---|
| link | 框序=级表顺序；每框两行数字；尾框=级联总计；连线首尾相接 |
| testsetup | 仪器按角色分列；连线落在端口小圆点上；损耗/长度与 JSON 一致；`▎CAL` 在声明了校准面的边上 |
| annotate | 底图拖不动；三色圈罩住目标；右栏意见卡编号与圈一致；虚线连到 target |
| stackup | 层序自顶向下；厚层明显更高；右栏标注与 JSON 一致；线宽箭头在信号层上 |

## 2. ADS 前仿链：五步人机回路（`rfauto ads-circuit`）

这条链的重点不是"把图画出来"，而是**让人参与前仿调参**：图就是参数
面板，你在 draw.io 里改值，rfauto 负责把改动变成网表、调 ADS 求解、
把指标写回图上，你看完指标再改。

```
J1 出图  →  J2 你在 draw.io 里改值  →  J3 跑（网表 → hpeesofsim → 指标）
   ↑                                                        ↓
   └──────────── J5 迭代：看指标卡，再改 ←── J4 反标注（指标上图）
```

v1 支持两个模板族：`wilkinson_snp`（Touchstone 直通，任意 N 端口）与
`branchline_cascade`（入线 TLIN → 4 端口 SnP → 出线 TLIN，可调线阻抗、
电长度、参考频率）。谐波平衡与有源链模板不在本回路范围内。只有 J3 需要
ADS（本仓对齐 ADS 2027 的 hpeesofsim）；J1、J2、J4 都不碰 ADS。

### J0 准备一份 Touchstone

`.s2p/.s3p/.s4p` 文件被 `.gitignore` 排除，仓里不带现成数据。你可以用自己 HFSS/
openEMS 导出的 S 参数（wilkinson 族任意端口数，branchline 族必须 4 端口），
或者先用仓内闭式基准生成器造一份参考数据：

```bash
mkdir -p runs/adsckt/demo
.venv/Scripts/python.exe -c "from rfauto.linkage.ads_template_family import build_wilkinson_touchstone as b; b('runs/adsckt/demo/wilk_ref.s3p', n_points=41)"
.venv/Scripts/python.exe -c "from rfauto.linkage.field_circuit_anchor import build_branchline_touchstone as b; b('runs/adsckt/demo/bl_ref.s4p', n_points=41)"
```

实测：这份 `wilk_ref.s3p` 与仓内 ADS 真机冒烟档案
`runs/aurora_o/t04_real_smoke/wilk_ref.s3p` **逐字节相同**——所以下文
J3/J4 引用的真机数字，就是你在装了同版本 ADS（ADS 2027）的机器上照做
会得到的数字。

### J1 出图：参数化电路图

```bash
rfauto ads-circuit diagram --family wilkinson_snp \
  --snp runs/adsckt/demo/wilk_ref.s3p --out runs/adsckt/demo/ckt.drawio --json
rfauto ads-circuit diagram --family branchline_cascade \
  --snp runs/adsckt/demo/bl_ref.s4p --out runs/adsckt/demo/bl_ckt.drawio --json
```

信封的 `values` 节逐参数给出当前值和来源。下面是 branchline 出图时加了
`--params '{"theta_out_deg": 55}'` 的节选（实测）——出图时就可以预置
参数，来源记为 `input-json`；不加 `--params` 则全是族缺省 `default`：

```
    "z_line": {
      "value": 50.0,
      "source": "default"
    },
    "theta_in_deg": {
      "value": 90.0,
      "source": "default"
    },
    "theta_out_deg": {
      "value": 55,
      "source": "input-json"
    }
```

wilkinson 的 `ckt.drawio` 与真机冒烟档案 `runs/aurora_o/t04_real_smoke/ckt.drawio`
逐字节相同。给 branchline 喂 3 端口文件会被拒：
`branchline_cascade 期望 4 端口 Touchstone，实读 3`。

图上的元件卡是带自定义属性的 UserObject，每个可调参数是三件组：
`p_<键>`（值）、`unit_<键>`（单位）、`src_<键>`（来源）。哪张卡承载哪个
参数：

| 族 | 卡 | 可调属性（`p_*`） |
|---|---|---|
| 两族共有 | Setup（黄色） | `p_sweep_fstart`、`p_sweep_fstop`、`p_sweep_npoints`、`p_sweep_unit`、`p_z0` |
| wilkinson_snp | Setup | `p_n_ports` |
| branchline_cascade | Setup | `p_f0_hz` |
| branchline_cascade | TLIN1（入线） | `p_z_line`、`p_theta_in_deg` |
| branchline_cascade | TLIN2（出线） | `p_theta_out_deg`（Z 与 TLIN1 同） |

频扫三项留空表示"随 Touchstone 的频带"——这是有意的缺项语义，不是漏填。
SnP 卡只显示文件名，真正喂给网表的文件由 J3 的 `--snp` 决定。

### J2 调图：在 draw.io 里改值（回路里由人做决定的一步）

这是整条链存在的理由，也是唯一需要你动手的地方：

1. 用 draw.io 桌面版（或 VS Code 的 Draw.io Integration 插件）打开
   `runs/adsckt/demo/bl_ckt.drawio`；
2. 选中 TLIN2 卡 → 右键 **Edit Data…**（Ctrl+M）；
3. 在属性表里找到 `p_theta_out_deg`，把 `45` 改成 `55` → **Apply**；
4. Ctrl+S 保存。卡上的标签用占位符（`%p_theta_out_deg%`）引用属性，
   改完即刷新；个别环境要重开文件才刷新。

几条规矩，违反了 J3 会如实报错而不是悄悄用错值：

- **只改 `p_*` 的值**。`unit_*`/`src_*` 是单位与来源，不要动；不要删
  `p_*` 属性——非频扫键被删时 J3 直接失败（实测：
  `图缺必带参数键 'z_line'（预期承载卡 uobj_tlin1；J2 编辑误删请恢复属性或重新出图）`）。
- **不要勾 File > Properties > Compressed**。rfauto 只读未压缩页。
- **不要手改网表**。图是唯一输入，网表是每次 J3 重新渲染的产物。
- 卡可以随意拖动、可以加自己的注记；白名单外的 `p_*` 属性会被忽略并
  在 `warnings` 里列出。

draw.io 的 Edit Data 对已带自定义属性的卡是"克隆原节点再改属性"，元素
名保持 `UserObject`，所以改完的图能被原样读回（已对照 draw.io 源码
EditDataDialog 的实现核对）。

### J3 跑：读图 → 合参 → 网表 → hpeesofsim → 指标 → 对拍（需要 ADS）

```bash
rfauto ads-circuit run --diagram runs/adsckt/demo/ckt.drawio \
  --snp runs/adsckt/demo/wilk_ref.s3p --out-dir runs/adsckt/demo/r01 --json
```

`run` 内部依次：读图里的 `p_*` → 三态合参 → 渲染网表 → hpeesofsim 求解 →
解析 → 系统指标 → 与确定性参考对拍 → 反标注（J4）。要点：

- **三态优先级**：`--params` 显式键 > 图上的值 > 族缺省。信封的
  `effective` 节逐键标来源（`input-json`/`diagram`/`default`），这是你
  核对"我改的值到底生效没有"的地方。例如图上 `theta_out_deg=55`、命令
  再加 `--params '{"theta_out_deg": 70}'`，生效的是 70、来源
  `input-json`，网表出线一行实测为 `TLIN:TLIN2  N_C N_D  Z=50 Ohm E=70 F=2.4 GHz`。
- **`--out-dir` 必填**（缺省拒跑，防止产物落进 runs 湖根）；`--diagram`
  只读，产物都写进 `--out-dir`：`<族>_netlist.txt`、`<族>_netlist.txt.ds`、
  `<族>_hpeesofsim_stdout.txt`、`<族>_result.json`、`<族>_circuit_result.json`
  和反标注图 `<族>_circuit.drawio`（另有 ADS 自身的中间文件）。
- **`--family` 核对**：显式给了且与图内族名不一致即报错（实测
  `图内 family='wilkinson_snp' 与显式 --family='branchline_cascade' 不一致`），
  防止拿错图。
- **对拍**：缺省开启（wilkinson=Touchstone 直通、branchline=闭式级联参考），
  门 `max|ΔS|` 缺省 1e-3，可用 `--gate` 调、`--no-compare` 关。
- **ADS 在哪**：`--ads-dir` → 环境变量 `RFAUTO_HPEESOF_DIR` →
  `configs/settings.yaml`（及本机覆盖 `settings.local.yaml`）的
  `hpeesof_dir` → 缺省安装路径，依次找第一个可用的。settings 按当前目录
  相对读取，所以**真机一律在仓根执行**（或显式设 `RFAUTO_HPEESOF_DIR`）；
  真机求解不要和其它求解并发跑。

**没装 ADS 会怎样？**（实测：无 ADS 的隔离环境下跑上面同一条命令）——
退出码 1，信封 `ok=false`，`ads.status=error` 并给出环境自查提示
`找不到可用 ADS 安装(需含 hpeesofsim.exe + tools/python/python.exe)…可用环境变量 RFAUTO_HPEESOF_DIR 指定`；
但**网表照样渲染出来**（`r01/wilkinson_snp_netlist.txt` 可直接检查你的
改值有没有进网表），反标注图降级成红色的错误头卡，不虚构任何指标。

**装了 ADS 时的真机结果**（仓内档案 `runs/aurora_o/t04_real_smoke/run/`，
输入与 J0/J1 产物逐字节相同；hpeesofsim 求解约 1.3 s）：反标注图上的卡
片标签原文——

```
前仿指标（wilkinson_snp） / sweep: 1.6–3.2 GHz × 41 点（source=touchstone） / status=ok  n_points=41  ports=3
system_gain_db = -3.05899 dB
input_vswr = 1.20932 1
amplitude_balance_db = 1.48391e-15 dB
output_phase_balance = 0 deg
对拍 max|ΔS| = 4.33556e-16 / 门 0.001 gate_ok=true
```

读法：`system_gain_db` 是端口 1→2 的 |S21| 带内 dB 均值——理想等分
功分器每路约 −3 dB，这里 −3.06 dB；两输出幅度/相位平衡在数值精度内为
零；ADS 解出的 S 参数与 Touchstone 直通参考差 4e-16（远低于门 1e-3）
——说明"图 → 网表 → ADS"这条链没有在半路改坏数据。

### J4 反标注：指标写回图上

`run` 结束时自动把指标写回图（产物是 `--out-dir` 里的
`<族>_circuit.drawio`，原图不动）。新增的是一个叫 `annot_sim` 的图层，
放在右栏：一张头卡（族名、频扫快照、状态）、每个指标一张卡、一张对拍
卡。每张数值卡都带 `value`/`unit`/`source`/`sim_ref` 属性——在 draw.io
里 Edit Data 能看到这个数字是哪个函数、哪个数据集算出来的；对拍不过
（`gate_ok=false`）的卡是红色。

只想重画指标、不想重跑仿真（比如换了底图、或复核别人的结果）时，用
`annotate` 叶离线反标注：

```bash
rfauto ads-circuit annotate --diagram runs/adsckt/demo/ckt.drawio \
  --result runs/aurora_o/t04_real_smoke/run/wilkinson_snp_circuit_result.json \
  --out runs/adsckt/demo/ckt_annotated.drawio --json
```

人读输出（实测）：

```
离线反标注  指标卡 6 张  层 annot_sim（幂等替换不堆积）
```

实测三点：这份离线产物与真机 run 自带的反标注图**逐字节相同**；对已
反标注的图再反标注，`annot_sim` 层被整体替换、不会越叠越多；
`--out` 与 `--diagram` 同路径会被拒绝。`--result` 要给 `run` 产出的
`<族>_circuit_result.json`（带指标节），不是 `<族>_result.json`。

### J5 迭代：看指标卡，再改，再跑

最顺手的做法是直接在上一轮的反标注图上改：打开
`runs/adsckt/demo/r01/<族>_circuit.drawio`，看完指标卡，Edit Data 改
`p_*`，保存，然后把它当 `--diagram` 跑下一轮，`--out-dir` 换一个新目录
（每轮一个目录，历史结果都留着）：

```bash
rfauto ads-circuit run --diagram runs/adsckt/demo/r01/wilkinson_snp_circuit.drawio \
  --snp runs/adsckt/demo/wilk_ref.s3p --out-dir runs/adsckt/demo/r02 --json
```

旧的 `annot_sim` 层会被新一轮替换（实测回灌后图里恰好一个
`annot_sim`）。每轮跑完先看信封 `effective` 节确认改动生效（来源应为
`diagram`），再看指标卡判断方向。

一个判读上的提醒（用离线替身实测过）：branchline 的出线/入线是匹配的
无耗 50 Ω 线时，改电长度 θ 只转相位，`system_gain_db`/`input_vswr` 的带内
均值不会变——θ 取 55°、60°、70° 三档指标逐位相同。这是物理，不是回路
没生效（网表里 `E=` 确实变了）。想看到指标卡动，改 `p_z_line`（失配）
——z_line 从 50 改到 35 后两项指标都随之变化。

## 3. 设计回放报告（`rfauto design-report`）

### 3.1 跑起来

给一个 run（`runs/` 下的目录名，或 run 目录路径）。还没有 run 的话，先按
`docs/tutorials/first_optimization_loop.md` 用 fake 通道跑一个优化。

```bash
rfauto design-report 20260830_213813_1510dee6
rfauto design-report 20260830_213813_1510dee6 --json
```

缺省把报告写到 `runs/<run_id>/design_report.md`；`--out` 可另指路径。
人读输出（实测，示例 run 为 fake 通道的 Wilkinson 功分器调参）：

```
设计回放报告  run=20260830_213813_1510dee6  design_verdict=FAIL  门 PASS 0/FAIL 2  freshness=legacy
```

`--json` 信封（节选）：

```
  "schema": "rfauto-design-report/v1",
  "diagrams": {
    "status": "missing",
    "attachments": []
  },
  "design_verdict": "FAIL",
  "n_gates_pass": 0,
  "n_gates_fail": 2,
  "freshness": {
    "status": "legacy",
```

几种你可能遇到的结果：

- **freshness 三态**：`fresh`（有收官指纹且对得上）、`legacy`（老 run 没有
  指纹，放行并注记）、`stale`（产物被改过，**拒绝出报告**，信封
  `stage="freshness_gate"`）——交付错配不能静默通过。
- run 不存在：`run 目录不存在: …（传 run_id 或 run 目录路径）`，信封
  `hints` 里给出排查路径（`ls runs/`、`rfauto runs verify` 等）。
- 报告对 run 目录是只读的：唯一写面是 `design_report.md` 本身，以及（仅当
  run 里有链路级数据时）`diagrams/` 附件；`--no-diagrams` 连附件也不写。
  实测用 `--out` 重定向时，run 目录里所有文件的大小和修改时间前后不变。

### 3.2 报告结构导读（六节）

报告开头四行：run 目录、生成时间（**唯一**不参与逐字节复现的一行）、
freshness、汇总判定 `design_verdict`。然后是六节：

| 节 | 内容 | 读的时候注意 |
|---|---|---|
| ① 设计目标与配方摘要 | 基本信息（model/adapter/study/status/git）、名义参数与优化范围、设计目标表 | 全部取自 `meta.json` 与 `recipe.snapshot.yaml`（run 收官时的快照，不是 `recipes/` 原件） |
| ② 优化轨迹回放 | 逐 trial 参数与 cost、best-so-far（↓ 标改进）、关键改进事件、收敛汇总量 `auc_norm`/`conv_ratio` | trial 文件只含成功 trial，剪枝/失败的不落文件，报告不虚报总数；汇总量是记账统计，不替你下"已收敛"结论 |
| ③ 最终设计与 verdict 门表 | 最终设计=cost 最小的 trial；与 `meta.json` 交叉核对；逐目标门表（观测值、违约量、PASS/FAIL/UNKNOWN） | 有 FAIL 即 FAIL；缺指标键记 UNKNOWN，不凑 PASS；违约量之和应等于 cost（报告自证一致性） |
| ④ 电路图总结 | run 里有链路级级表（`chain.json`/`link_chain.json`，或某个 `*.json` 的 `chain` 键，级三键 name/gain_db/nf_db）时自动出 `diagrams/link_summary.drawio` | 普通优化 run 没有这类数据，本节如实标 `missing` 并给出手工出图命令（即 §1.1 的 `rfauto diagram link`），不猜、不造数字 |
| ⑤ 敏感性 / trade-off 摘要 | 各参数在 trial 内的跨度、参数与 cost 的 Pearson r | 样本少于 12 时强制标"低样本探索性统计"，r 只陈列不解释 |
| ⑥ 复现命令附录 | `rfauto replay`、`rfauto repro export`、`rfauto runs verify`、本报告再生成、`rfauto reports render`；配方快照指针；环境指纹 | 复现以 run 内快照为准 |

**来源标注怎么读**：报告里每个数字后面都跟着来源，三类写法——
`文件名:JSON 路径`（直接从 run 湖读，如 `trials/trial_6.json:cost`）、
`derived:<公式>@REPORT_SPEC §n`（按钉死的公式派生，可复算）、
`service:<函数名>`（复用既有服务的产出）。看到一个数字有疑问，按来源
回到原文件核对即可。

### 3.3 与既有报告面的分工

- `rfauto design-report`：优化族 run（有 `trials/`，但没有
  `results/metrics.json`）此前没有报告出口，本叶补的就是这块；
- `rfauto report`：单次评估的 run（有 `results/metrics.json`）继续用它；
- `rfauto reports render`：既有的 PDF/HTML 双输出报告链。

报告里会写出本机的 run 目录绝对路径，**外发报告前自己检查一遍路径信息**。

## 附：选型速查

| 我想…… | 用 | 关键输入 | 产物 |
|---|---|---|---|
| 画接收/发射链路框图，并标出逐级与级联增益/噪声系数 | `rfauto diagram link` | 级表（name/gain_db/nf_db） | `.drawio`（数字=Friis 内核） |
| 画实验室测试连接（VNA/频谱仪/LISN/线缆/校准面） | `rfauto diagram testsetup` | 场景 JSON | `.drawio`（损耗/长度原值） |
| 在已有图或截图上做评审批注，不动原图 | `rfauto diagram annotate` | 底图 + 标注 JSON | 双层 `.drawio`（底图锁定） |
| 画 PCB 叠层横截面，顺带标 50 Ω 线宽 | `rfauto diagram stackup` | 叠层 JSON（+ `--width-synth`） | `.drawio`（线宽=综合内核） |
| 在图上改参数、用 ADS 前仿、看指标再改 | `rfauto ads-circuit diagram` → draw.io → `ads-circuit run` | 模板族 + `.sNp` | 网表、`.ds`、反标注 `.drawio` |
| 不重跑仿真，只把已有结果画回图上 | `rfauto ads-circuit annotate` | 图 + `<族>_circuit_result.json` | 反标注 `.drawio` |
| 给一次优化出一份带来源的设计总结 | `rfauto design-report` | run_id | `design_report.md` |

常见坑：

- `--out` 的父目录不存在 → 先 `mkdir -p`；
- 在 draw.io 里勾了 Compressed → 读回报错，取消勾选重存；
- 改了 `p_*` 却没生效 → 看 J3 信封 `effective` 的来源列是不是 `diagram`，
  以及是不是被 `--params` 覆盖了；
- 在别的目录跑 `ads-circuit run` 找不到 ADS → 回仓根或设 `RFAUTO_HPEESOF_DIR`；
- design-report 报 `stale` → 产物与收官指纹对不上，先 `rfauto runs verify <run_id>` 查哪里变了。

（v1 这三个面只有 CLI 与 service 两种入口，MCP 工具尚未接线。）

## 下一步

- 级联预算更完整的指标（IIP3/OIP3、SFDR、灵敏度）：`docs/how-to/cascade-budget-and-spur.md`
- 判读三态与 verdict 门的语义：`docs/tutorials/verdict_semantics.md`
- 产出可回放的优化 run（§3 的输入）：`docs/tutorials/first_optimization_loop.md`
