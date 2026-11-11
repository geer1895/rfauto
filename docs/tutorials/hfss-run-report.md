# HFSS run 四联图：S 参数 + 相位 + 群时延 + εeff 一键出图

> 本文每条命令都在开发环境实测过（退出码逐条核对，2026-11-07）。它解决一个
> 真实借用者卡过的痛点：跑完 HFSS 想要「S 参数 + 相位 + 群时延 + εeff」
> 四联图，工具里没有现成入口，四张图只能手写 matplotlib——现在
> `rfauto reports run-figures` 一条命令出齐，JSON 信封把每步口径落档。
> 英文版（English version）：docs/tutorials/hfss-run-report_en.md。

赶时间的话：第 2 节一条命令出四联图；第 3 节解释 εeff 联为什么缺省
跳过（参考面跨度纪律，手拍线长会错 5 倍以上）。

## 0. 前置

- 已完成 `docs/tutorials/getting-started.md` 第 1-2 节（安装 +
  `rfauto doctor` 体检）。
- 全程**零 license、零求解器**：本命令是纯后处理，输入是已有的 S 参数
  数据（Touchstone 文件或 rfauto run 目录）。
- 数据从哪来（三选一）：
  1. `rfauto run` 产物——run 目录里 `results/params.sNp`（Touchstone，
     端口数随模板）或 openEMS 通道的 `sparams.csv`；
  2. HFSS / 其他 EDA 导出的 Touchstone（`.s2p`–`.s10p`）；
  3. 任何 openEMS 模板 run 目录（`sparams.csv` 掩码口径优先装载）。

## 1. 四联图是什么

一张 PNG（IEEE 全宽 2×2 版面），四联：

| 联 | 内容 | 口径 |
|---|---|---|
| 1 | S 参数幅值 | \|S11\|、\|S21\|（dB vs 频率） |
| 2 | S21 相位 | 展开相位（`np.unwrap`，deg vs 频率） |
| 3 | 群时延 | τ = −dφ/dω（中心差分 + 可选 Savitzky-Golay 相位平滑） |
| 4 | εeff | εeff = (β/ω)²·c²，从 S21 相位提取（需声明参考面跨度，见第 3 节） |

铁律：全部数字出自数据源本身——差分/平滑/εeff 公式都是声明式参数，
随 JSON 信封 `notes` 逐条落档，读图时可直接核对口径；同输入两跑 PNG
逐字节一致（零时间戳零随机，dpi/尺寸走 `plot_style` 单源）。

## 2. 一条命令出四联图

**路径 A：手里是 Touchstone 文件**（示例数据 = 一条 50 mm 参考跨度、
εeff 真值 2.10 的合成有耗线 .s2p，用于核对提取链）：

```bash
rfauto reports run-figures msline.s2p --ref-span-m 0.05
```

**你会看到**（实测）：

```text
✓ 四联图: msline/hfss_run_figures/hfss_run_figures.png
  源 touchstone n=181 点 1–10 GHz  2 端口
  |S21| -0.4…-0.4 dB  相位 -87…-870 deg
  εeff (scalar): 2.1  L=0.05 m
```

产物缺省落在**源文件旁** `hfss_run_figures/` 子目录，文件名恒为
`hfss_run_figures.png`（确定性命名，重跑覆盖同路径）。

**路径 B：rfauto run 目录直读**（wilkinson 模板全链实测，零 license）：

```bash
rfauto templates export-recipe wilkinson --out my_wilk.yaml
rfauto validate my_wilk.yaml
rfauto run my_wilk.yaml --adapter fake      # 秒级，run 目录落 runs/<run_id>
rfauto reports run-figures runs/<run_id>
```

**你会看到**（实测，run_id 每次生成）：

```text
✓ 四联图: runs/20261107_121606_0b227c1d/results/hfss_run_figures/hfss_run_figures.png
  源 run_dir_touchstone n=201 点 1–4 GHz  3 端口
  |S21| -3.24…-9.81 dB  相位 -40.9…-163 deg
  εeff: 跳过（--ref-span-m 未声明，零手拍口径）
```

wilkinson 是 3 端口器件：缺省 `--s21 1,2` 取「输入→直通臂」；要看
「输入→耦合臂」加 `--s21 1,3`（端口号记进 JSON `summary.s21.ports`）。

## 3. εeff 联：为什么缺省跳过（参考面跨度纪律）

εeff 的口径是

```text
εeff = (β/ω)²·c² ，  β = |∠S21 展开相位| / L
```

**L 必须取参考面跨度 = 两个端口面之间的距离**，不是画图的名义线长。
S21 的相位含全部馈段电长度——本仓有真实先例：名义 40 mm 的线，端口面
实测跨度约 93 mm，L 手拍名义线长直接错 5.4 倍。所以本命令**缺省不猜
长度**：不给 `--ref-span-m` 就跳过 εeff 联（PNG 第 4 联落 skip 注记、
JSON `notes` 落同款注记、console 提示「零手拍口径」），宁缺不猜。

L 从哪来：

- **HFSS**：参考面在波端口面上——量两个端口面沿传输线方向的距离
  （建模时端口面坐标差一眼可读）；
- **openEMS run**：查 `port_ut_*` 文件头的 `start-coordinates`（端口面
  实际落格坐标，是比渲染字面量更可信的直接测量）。

给了 `--ref-span-m` 之后，第 4 联还有自动二分：

- 逐点 εeff 相对散布 `(max−min)/|median| ≤ 0.05` → **标量**模式：JSON
  出 `value`（中位数），PNG 叠加红色中位虚线；
- 否则 → **曲线**模式：JSON 出 `median/min/max`，PNG 逐点曲线
  （色散明显的真实微带常见，散布阈值 0.05 固定，随 notes 落档）。

核对锚（实测）：上面 εeff=2.10 的合成线提取回
`2.1000000000041`（相对散布 9.3e-10 → 标量）——提取链对无耗/弱耗
解析线是精确的。

## 4. 参数一览（与 `--help` 逐项核对）

| 参数 | 缺省 | 说明 |
|---|---|---|
| `source`（位置参数） | 必填 | Touchstone 文件（`.s2p`–`.s10p`）或 run 目录 |
| `--ref-span-m` | 不给 | 参考面跨度 m（端口面间距）；不给则 εeff 联跳过（第 3 节） |
| `--s21` | `1,2` | S21 端口对 `from,to`（1 起物理口号；skrf 约定 `s[to, from]`） |
| `--gd-smooth` | `1` | 群时延相位平滑窗点数（Savitzky-Golay，polyorder=2）；`1`=关闭 |
| `--out-dir` | 源旁 `hfss_run_figures/` | 产物目录（目录自动创建） |
| `--json` / `-j` | 关 | JSON 信封输出（第 5 节） |

`--gd-smooth` 使用直觉：

- 真实数据相位有噪声时开 9–15 常见；线性相位分量在平滑下**精确不变**
  （2 阶多项式基含线性），只平滑噪声；
- 偶数入参自动上调为奇数、超过频点数自动截断——两者都在 `notes` 里
  记录（实测 `--gd-smooth 8` → 注记「偶数入参已上调为奇数 9」）。

产物目录细则：run 目录源时产物跟**实际装载到的文件**走——
`sparams.csv` 源落 run 目录根的 `hfss_run_figures/`；
`results/params.sNp` 源落 `results/hfss_run_figures/`。

## 5. 输出解读

### 5.1 控制台摘要

即第 2 节「你会看到」：源类型、频点数、频带、端口数、|S21| 与展开相位
的起止值、εeff 行（标量值/曲线中位数/跳过原因）。

### 5.2 JSON 信封（`--json`）

```json
{
  "ok": true,
  "png_paths": ["msline/hfss_run_figures/hfss_run_figures.png"],
  "summary": {
    "source_kind": "touchstone",
    "n_ports": 2,
    "n_freqs": 181,
    "f_min_ghz": 1.0,
    "f_max_ghz": 10.0,
    "s11_db":  {"port": 1, "min": -33.01, "max": -33.01},
    "s21": {"ports": [1, 2], "mag_db_min": -0.4, "mag_db_max": -0.4,
            "phase_unwrap_start_deg": -87.01, "phase_unwrap_end_deg": -870.08},
    "group_delay": {"median_ps": 241.69, "min_ps": 241.69, "max_ps": 241.69,
                    "smooth_window": 1},
    "eps_eff": {"mode": "scalar", "rel_spread": 9.34e-10, "ref_span_m": 0.05,
                "method": "eps_eff=(beta/omega)^2*c^2, beta=|unwrap(angle(S21))|/ref_span_m",
                "value": 2.1000000000040737},
    "png_path": "msline/hfss_run_figures/hfss_run_figures.png",
    "notes": ["…口径注记，见 5.3…"]
  }
}
```

（节选自实测输出；`source_path`/`png_path` 为绝对路径，此处缩短。）

`summary` 键速览：

| 键 | 含义 |
|---|---|
| `source_kind` | `touchstone`（文件）/ `run_dir_touchstone` / `sparams_csv` |
| `s11_db` | \|S11\| dB 的 min/max（恒对端口 1） |
| `s21` | 端口对、\|S21\| dB min/max、展开相位起止；**1 端口数据为 null** |
| `group_delay` | 群时延中位/min/max（ps）+ 实际生效平滑窗 |
| `eps_eff` | 标量出 `value`；曲线出 `median/min/max`；未声明 L 或 1 端口为 null |
| `notes` | 全部口径注记（下一小节） |

### 5.3 notes：口径自描述

`notes` 逐条落档本次运行的口径，典型三条（实测原文）：

- `|S| dB 地板 -200（|S| 零点防 log0，仅绘图/摘要面）`——显示面地板，
  不是数据改动；
- `群时延 = -dφ/dω（np.gradient 中心差分+edge_order=2 二阶端点）+
  Savitzky-Golay 相位平滑窗 1 点 polyorder=2（关：1=缺省关闭）…`——
  平滑窗实际生效值以此为准；
- `εeff = (β/ω)²·c² …；L=0.05 m 由调用方显式声明…标量/曲线阈值
  eps_scalar_spread_tol=0.05（相对散布实测 9.34e-10 → scalar）`——
  L 声明值、散布实测值、模式判定全在档。

## 6. 源的三种形态

| 形态 | 装载顺序 | 说明 |
|---|---|---|
| Touchstone 文件 | 直接读 | 只收 `.s2p`–`.s10p`；**`.s1p` 文件不收**（错误表第 2 条） |
| run 目录（有 `sparams.csv`） | csv 优先 | openEMS 掩码口径（部分矩阵，单激励），不回退 Touchstone |
| run 目录（无 csv） | `results/params.s*p` → 目录内 rglob `.s2p/.s3p/.s4p` | 首个可解析者胜出 |

**1 端口 run 目录**（如 pifa 天线的 `results/params.s1p`）合法但如实
降级（实测）：只出第 1 联 |S11|，S21 相位/群时延/εeff 三联跳过
（PNG 落「eps_eff panel skipped / 1-port data: S21 unavailable」注记、
JSON `s21`/`eps_eff` 为 null），`ok` 仍为 `true`，退出码 0。

## 7. 常见错误排除（错误消息全部实测）

| 症状 | 实测错误原文（节选） | 处置 |
|---|---|---|
| 路径写错 | `源装载失败: 源不存在: <路径>` | 核对路径；run 目录传目录不传文件 |
| 1 端口 Touchstone 文件 | `不支持的源文件类型 '.s1p'（须为 Touchstone ('.s2p', …)` | 文件形态最低 .s2p；纯 1 端口数据放进 run 目录 `results/params.s1p` 走目录形态（第 6 节） |
| 目录里没有产物 | `run 目录内未找到 sparams.csv 或 Touchstone 产物` | 确认是 rfauto run 目录（有 `results/params.sNp` 或 `sparams.csv`） |
| 文件名端口数与数据块不符 | `cannot reshape array of size … into shape …` + 建议（#248） | skrf 按扩展名推断端口数：1 端口数据写成 .s2p 即此错；改对扩展名或补全数据块（2 端口 RI 每行 9 列） |
| `--s21 3`（只有一个数） | `--s21 须为 from,to 两整数，实际 '3'`（退出码 2） | 写成 `--s21 1,3` 形态 |
| `--s21 1,1` | `S21 端口对 from,to 不得相同（实为 1,1）` | 传播需要两个不同端口 |
| `--s21 1,5`（越界） | `S21 端口号 5 越界（数据 2 端口，物理口号 1..2）` | 口号 1 起且 ≤ 数据端口数 |

## 8. 边界（如实）

- **εeff 联缺省跳过**——要出 εeff 必须显式 `--ref-span-m`（第 3 节）。
- **εeff 口径假设**：波端口数据参考面已嵌在端口面上（S21 相位 = −β·L）；
  若 Touchstone 文件自带非零参考偏移（port de-embed 未做），εeff 结果
  含偏置——工具如实不修正，读数时要知道这一层。
- 频率轴须**严格单调递增且 ≥2 点**（展开相位/数值差分的前提），乱序
  如实报错不硬算。
- εeff 近常值（散布低于 fp 噪声量级）时第 4 联 y 轴自动缩到噪声量级
  （近常值曲线显示地板，纯显示 cosmetics），中位图例可能被裁切——
  数值以 JSON `summary.eps_eff` 为准。
- 曲线/标量判定阈值 0.05 是 service 层固定参数，CLI 未暴露（随 notes
  落档可复核）。
- 相邻命令的关系：要 run 的完整报告（四段式大纲 + provenance）用
  `rfauto reports render`（见 `docs/tutorials/design_report.md`）；要
  SI 通道指标（无源性/因果性/TDR/COM）用 `rfauto si report`——三者
  消费同一套源装载面，输入形态一致。

## 9. 一页速查

| 想做什么 | 命令 |
|---|---|
| 出四联图（Touchstone） | `rfauto reports run-figures <文件.s2p> --ref-span-m <L_m>` |
| 出四联图（run 目录） | `rfauto reports run-figures runs/<run_id> [--ref-span-m <L_m>]` |
| 换 S21 端口对 | `--s21 1,3`（1 起物理口号） |
| 相位噪声大时平滑群时延 | `--gd-smooth 9`（1=关；偶数自动上调奇数） |
| 指定产物目录 | `--out-dir <目录>`（缺省源旁 `hfss_run_figures/`） |
| 机器可读输出 | `--json`（信封含 summary/notes 全口径） |
| run 完整报告（PDF+HTML） | `rfauto reports render runs/<run_id>` |
