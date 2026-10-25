# UI 工作台导览：第一次打开 rfauto 看板

> 写给第一次打开 rfauto 人工核验 UI 的你。文中的页面清单、主题名、快捷键
> 均按当前版本前端源码逐项核对（`index.html` 的导航注册表、`palette.js`、
> `pages.js`）；启动命令与旗标经 `rfauto ui --help` 实测。读完你将知道：
> 怎么启动、侧栏二十多个入口各是干什么的、主题怎么换、命令面板怎么用、
> 3D 预览和图表怎么交互、出问题去哪自查。
> 英文版（English version）：docs/tutorials/ui_workbench_tour_en.md
> （W9-S3 译，2026-10-19 复核同笔）。

## 0. 前置

- 已按 docs/tutorials/getting-started.md 装好环境（`.venv` + `pip install -e .`）。
- 现代浏览器任意一款（Chrome/Edge/Firefox 均可）。
- 不需要 HFSS/ADS license——UI 本身只是看板，看 fake 数据零门槛。

## 1. 启动（1 分钟）

```bash
# git-bash（Windows，未激活 venv 的写法）
.venv/Scripts/rfauto.exe ui --port 8765

# 已 source .venv/Scripts/activate 的直接
rfauto ui
```

注意：`python -m rfauto` 不是有效入口（包没有 `__main__`），UI 一律走
`rfauto` 命令（console script，pyproject `[project.scripts]` 注册）。

启动成功会打印：

```
rfauto UI → http://127.0.0.1:8765/（Ctrl+C 退出）
```

并自动打开浏览器（默认 `--open`；不想自动弹窗加 `--no-open`，手动访问打印的地址）。

`rfauto ui --help` 实测旗标一览（逐项核对过）：

| 旗标 | 缺省 | 说明 |
|---|---|---|
| `--port` / `-p` | 8642 | 监听端口 |
| `--host` | 127.0.0.1 | 监听地址（默认仅本机） |
| `--open` / `--no-open` | open | 启动后是否自动开浏览器 |
| `--expose-runs` / `--no-expose-runs` | 三态缺省 | runs/ 目录静态服务开关：缺省=回环绑定开、非回环绑定关（开源默认安全）；非回环显式 `--expose-runs` 才整目录暴露 |

## 2. 认识导航：三组入口

侧边栏按「工作区 / 分析 / 帮助与系统」分三组，共 26 个入口（25 个可见 +
1 个隐藏的「Run 详情」页——点 Run 历史里的行才进入）。每个入口对应一个
页面，浏览器地址栏会同步成 `#/页面id` 形式的深链（如 `#/runs`），刷新、
分享链接都保持当前页；未知值回落总览。部分页支持参数级二级深链
（`#/detail/<run_id>`、`#/tools/<键名>`、`#/campaign/<runId>`），见各页说明。

**工作区**（从建模到推进的主干道）：

| 页面（侧栏名） | 深链 id | 一句话 |
|---|---|---|
| 总览 | `#/dashboard` | 可拼装的组件看板（KPI/最近 run/S11 趋势/求解器/调参状态等），「＋ 添加组件」勾选，拖拽排序，自动记忆 |
| 工程导入 | `#/import` | 读入 HFSS 工程（.aedt）：变量/扫参范围/端口 → 设计规格 + 配方草稿 |
| 配方编辑 | `#/recipe` | 配方目录点选加载，参数表改值即时刷新 3D 预览；保存并运行（fake/openEMS/HFSS） |
| 优化调参 | `#/tune` | 表单式起调参：配方 + adapter（fake/hfss/openems）+ trials + sampler；下方 trial 实时监控每 3 秒刷新收敛曲线 |
| 优化洞察 | `#/optstack` | 选一个优化 run：Pareto 前沿散点（nsga2 直读，含逐代超体积收敛）+ 两参数成本/可行性热图 |
| 执行看板 | `#/loopboard` | 自治环（propose→verify→fix）观察面：里程碑验收 + 暂停/继续/接管（协作式，步骤边界响应） |
| 战役仪表盘 | `#/campaign` | 带 trials 审计的调参/优化 run：座位状态（PASS/SKIP/FAIL 三分）+ 成本热图 + trial 虚拟列表（千行滚动） |
| 调度队列 | `#/queue` | 战役队列 + 决策日志（只读） |
| 模板画廊 | `#/gallery` | 全部器件模板的交互卡（与 docs 模板元数据同源，75 模板）；白名单模板可滑块改值看闭式即时预览（零 EM 求解） |

**分析**（看数据、下钻产物）：

| 页面 | 深链 id | 一句话 |
|---|---|---|
| Run 历史 | `#/runs` | 每行=一次仿真；顶部按 run_id 文本、通道、S11 阈值过滤 |
| Run 详情 | `#/detail`（隐藏） | 单 run 下钻：S 参数曲线、3D 模型、产物清单、配方快照 |
| S 参数分析 | `#/sparams` | 交互曲线：图例点选显隐、滚轮+滑块缩放、悬停读数；dB/相位模式；Smith 圆图；可导入外部 .sNp 叠加 |
| 远场方向图 | `#/farfield` | openEMS nf2ff 产物视图：极坐标切面、Dmax/η/HPBW 等指标 |
| 场可视化 3D | `#/field` | DumpHDF5 三轴中面 |E| 切片（滑块+等值线）与等值面 3D；远场 3D 体 |
| 校准工作台 | `#/calibration` | 校准产物一览：gate 判定、LOOCV ρ、样本量；点行看参数空间散点与验证点偏差 |
| 数据集 | `#/datasets` | runs/datasets 注册表只读清单 + 行级预览（注意：预览 n_rows 是抽样返回行数，非全量计数） |
| 标定锚 | `#/anchors` | 物理标定锚注册表（knowledge/anchors.yaml）只读：active/stale/experimental 等状态一览 |
| UQ 不确定度 | `#/uq` | 代理蒙特卡洛公差分析：良率/指标分布/敏感性（不跑真机） |
| 代理 Playground | `#/playground` | 选已校准 run，拖参数滑条实时看代理预测（诚实标注：预测非真值） |
| 成本时间线 | `#/timeline` | 上图=每个 run 的 cost 按时间排列（按 adapter 分色）；下图=最近调参 run 的 trial 收敛 |
| 报告中心 | `#/reports` | 汇总 runs/ 下全部人读报告；长报告自动出目录；页底双 run 对比 |
| 微波工具箱 | `#/tools` | 闭式微波计算器交互面（与 CLI `rfauto calc`、MCP 同一内核）：按组下拉+搜索、自动画图/热图、扫参、`#/tools/<键名>` 深链——详见第 6 节 |
| Agent 助手 | `#/agent` | LLM 对话 + 工具调用；未配 API 时为指令模式；参数提案走三层 Gate 收件箱批准 |

**帮助与系统**：

| 页面 | 深链 id | 一句话 |
|---|---|---|
| 使用指南 | `#/guide` | 内置说明书：5 分钟上手路线 + 概念速查表 + 常见问题——第一次来先看这页 |
| 求解器 | `#/solvers` | 求解器注册状态（openEMS/Palace/HFSS 可用性 + 可视化产出数） |
| 剖析 | `#/profile` | py-spy 火焰图采样（附着 pid 或新起命令），产物落 runs/profile/ |

小贴士：每个页面顶部都有「❓ 本页说明（点开查看）」折叠块，是本教程的
页面级细化版；本篇讲不细的，以那块为准。

## 3. 主题：Midnight → Ocean → 浅色 → 跟随系统

侧栏底部「🌌 Midnight」按钮循环切换四态，顺序固定：

1. **🌌 Midnight**——深蓝暗色（缺省深色基底）
2. **🌊 Ocean**——青绿暗色
3. **☀ 浅色**——亮色
4. **🖥 跟随系统**——跟操作系统 `prefers-color-scheme` 走，系统变它跟着变

要点（源码实测口径）：

- 主题存浏览器 localStorage，键名 `rfauto-theme`；**没有存档时缺省=跟随系统**。
- 旧版本存过的 `dark` 会自动映射为 Midnight，不用手工迁移。
- 切到浅色时，图表调色板同步换浅色系，不会出现白底白线。
- 命令面板（下一节）里也有四条主题命令，可直接搜索跳转（命令全集
  20 条=主题 4+跳转 7+动作 9，钉在 test_ui_palette_cmds；W5-S17 动作
  扩充后口径，W9-S3 复核）。

## 4. 命令面板：Ctrl+K 全局跳转

按 **Ctrl+K**（macOS Cmd+K）或点侧栏「⌘ 命令面板」按钮打开。键位：

- `↑` / `↓` 选择，`Enter` 执行，`Esc` 关闭（点遮罩也关）；
- `Tab` 在面板内循环焦点，不会跑到面板外。

输入框支持三种前缀模式（提示条原文：`↑↓ 选择 · Enter 跳转 · Esc 关闭 · # run · > 命令 · Ctrl+K 开关`）：

| 输入 | 模式 | 能搜到什么 |
|---|---|---|
| 直接打字 | 页面+配方 | 全部导航页（按侧栏名或 id 匹配，Enter 跳页）；recipes/ 下的配方（Enter 进配方编辑页并自动加载） |
| `#` 前缀 | run | 最近 200 条 run（子串匹配，大小写不敏感），Enter 打开该 run 详情 |
| `>` 前缀 | 命令 | 当前命令集=20 条（主题 4 条 Midnight/Ocean/浅色/跟随系统+跳转 7 条+动作 9 条） |

最常用的三个动作：`Ctrl+K` → 打页面名回车跳页；`#<run_id 片段>` 直接下钻
某次 run；`>light` 切浅色。

## 5. 3D 预览与灯箱

**配方 3D 预览**（配方编辑页）：右侧 3D 视图由参数表驱动——改参数值
3D 即时重画（拖转视角、滚轮缩放），点「保存配方」才落盘。

**场可视化 3D**（分析组）：

- **切片**：三轴中面 |E| 热图（dB 相对体峰值），拖滑块改切片索引，等值线
  −3/−10/−20 dB 叠加（数值可改）。
- **等值面 3D**：鼠标**拖动旋转、滚轮缩放**；图例会标当前等值面 dB（相对
  峰值）、顶点/三角数与配色含义（蓝低→红高）。等值面渲染依赖可选依赖
  `rfauto[viz3d]`（PyVista/VTK），未安装时页面诚实降级为切片等值线，不是坏了。
- 数据源是 openEMS 真跑 run 的 DumpHDF5 产物——fake run 没有场数据，
  本页下拉里选不到属正常。

**灯箱**：任何地方点小图（如 Run 详情里的 PNG 曲线）会放大成灯箱；**点
任意处或按 Esc** 关闭。

**图表卡片**：曲线图统一带工具条——**CSV 导出**（数据平铺）、**PNG 导出**
（2x 分辨率）；图内交互：图例点选显隐系列、滚轮缩放、悬停十字线读数。

## 6. 微波工具箱：分组·搜索·画图·扫参·深链

「微波工具箱」（`#/tools`）是闭式微波计算器的交互面，与 CLI `rfauto calc`、
MCP `list_calculators`/`run_calculator` 同一内核——键清单与分组由注册表
**实时生成**（页面不手工维护，键数随内核扩键自动增长，本教程不钉死数字）。
架构批 批之后的完整形态：

- **按组浏览**：下拉按业务组分组（组序=常用在前，实验/其他恒殿后），
  每组带键数计数；组归属由 service 的 `group` 字段单源供给（CLI/MCP/UI
  三壳同享，不会三处各说各话）。
- **搜索**：顶部搜索框对键名/中文名/用途三字段实时子串过滤（大小写
  不敏感），旁有 `可见/总数` 计数器。
- **公式面板**：说明区给出中文名、键名、组徽章与一句话用途；description
  含公式的键会多一个「公式与出处」折叠块（原文等宽展示，可复制）。
- **单点计算+自动画图**：填参数点「计算」，结果出键值表；返回数组/曲线
  形态的键自动补折线图、复数方阵补热图（识别不了的形态如实只出表，
  不硬凑）。图表带 CSV/PNG 导出。
- **扫参模式**：勾选「扫参模式」→ 选一个数值参数 + 起点/终点/点数
  （2–101 点，缺省 21）→「扫描」逐点串行调 `/api/calculators/run`，
  出响应曲线+逐点表格；失败点如实标「跳过：原因」，不静默丢弃。
- **深链**：`#/tools/<键名>` 直达并选中某计算器（地址栏随选择同步，
  复制地址即分享参数面）；命令面板的「跳转：微波工具箱」也直达本页。

同一键的命令行等价（实测）：

```bash
rfauto calc list                          # 全部键+参数表+公式出处（--json 机读）
rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4 \
    -p epsilon_r=3.66 -p h_mm=0.508       # 单键执行；实验键需 --allow-experimental
```

## 7. 常见问题

- **端口被占 / 页面行为像旧版本**：八成是常驻旧实例还占着端口（旧进程
  带旧代码）。换端口重开最省事：`rfauto ui --port 8643`；确认不要旧实例时
  再按命令行核对着杀进程（Windows 下别整树连坐）。
- **主题切了不生效/样式错乱**：先硬刷新（Ctrl+Shift+R）；仍不行清一下站点
  localStorage（DevTools → Application → Local Storage → 删 `rfauto-theme`）
  再刷新——存档主题与新版本冲突时这一步重置为跟随系统。
- **Run 历史是空的**：先跑一次（见 first_optimization_loop 教程，fake 通道
  秒级）；UI 只展示 runs/ 索引里已有的 run。
- **曲线图看不到 S 参数**：fake 通道不产 Touchstone，去「Run 详情」看 PNG
  曲线；真 S 参数交互分析（含 Smith 圆图）在「S 参数分析」页，需要有
  Touchstone 产物的 run。
- **侧栏突然只剩图标**：窗口宽度 ≤900px 时侧栏自动收窄成图标态（省空间
  的既定行为），拉宽窗口即恢复，不是故障。
- **剖析页一直提示 py-spy 未安装**：该页是可选增强，`pip install py-spy`
  后刷新即可；不装不影响其他功能。

## 8. 下一步

- 想跑通第一次仿真与优化闭环（UI 看板正好用来观察）：
  docs/tutorials/first_optimization_loop.md
- 从安装开始走一遍：docs/tutorials/getting-started.md
- 想推进五阶段战役（UI 战役仪表盘对应的能力）：
  docs/tutorials/campaign-walkthrough.md
- 全部命令与模块的权威出处：docs/reference.md
