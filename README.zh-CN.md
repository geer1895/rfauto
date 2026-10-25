<p align="center">
  <img src="docs/assets/hero.svg" alt="rfauto — RF/微波设计自动化 + LLM 编排" width="100%">
</p>

# rfauto

[![tests](https://img.shields.io/badge/tests-27000%2B-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)]()
[![License](https://img.shields.io/badge/license-GPLv3-blue)]()
[![code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)]()

[English](README.md) | 简体中文

**rfauto 是一个射频/微波设计与仿真的自动化框架。** 描述你要的器件，它用物理公式
算出第一版尺寸，调用你手头有的求解器做仿真，自动检查结果是不是数值假象，再让
优化器把尺寸调到位——AI 助手可以通过 MCP 指挥整个流程，但只有一条铁律：

> **所有物理数字（频率、损耗、几何尺寸）都由确定性公式内核或求解器产生，
> 永远不由大语言模型编造。**

它把 **16 个电磁/EDA 引擎**接到同一个接口后面，内置 **75 个参数化器件模板**和
配套的物理验收判据，提供 **273 条 CLI 命令**和 **152 个 MCP 工具**（+9 个
resources），并靠 **27000+ 条单元测试**兜底验证——这些测试不需要任何商业许可
就能跑。

<!-- numbers-start（check_numbers 门控锚；实测注入，勿手改数字） -->
`CALCULATOR_REGISTRY 340 (with experimental 330)` · `TEMPLATE_META 75` · `EXPECTED_TEMPLATES 75` ·
`ANCHORS 87` · CLI 命令 280（叶子） · （157 个工具 + 10 个 resources）
<!-- numbers-end -->

**目录** · [为什么做](#为什么做这个) · [它能做什么](#它能做什么) ·
[信任层](#信任层) · [快速开始](#快速开始) · [Web UI](#web-ui) ·
[引擎](#引擎) · [文档](#文档) · [路线图](#现状与路线图) · [参与贡献](#参与贡献)

![架构](docs/assets/zh/architecture.png)

> 注：上下图示内嵌数字为历史快照，实时数字以 `rfauto doctor` 或
> `scripts/check_numbers.py` 为准。

## 为什么做这个

射频仿真日常充满重复劳动和悄无声息的坑：

- 每迭代一轮 = 重画几何 + 等几分钟到几小时的求解 + 手工抄数字；
- 每家商用工具各有一套 API 和怪癖，换引擎就要重写一遍流程；
- 求解器会"安静地"出错——网格不好、端口设错，产出的垃圾数据和真结果一样
  看起来很合理；
- 好用的求解器要商业许可，免费的求解器在验证之前又不敢信。

rfauto 把这个循环变成代码：模板负责建几何，适配层负责跟引擎打交道，质检门负责
判断结果可不可信，优化器负责闭环，报告里的每个数字都带出处。

## 它能做什么

- **一个接口，多家引擎** —— HFSS、ADS、openEMS、COMSOL、Elmer、NGSolve、
  Meep、Icepak、Q3D、Palace、KiCad、ngspice、FDTDX（JAX）、MMT（解析模基）、
  QucsatorRF、VNA 接在同一个适配层后面。
  商业引擎按需安装（可选依赖），核心功能全部跑在内置 fake 求解器上——零许可
  就能体验完整框架。
- **器件模板工厂** —— 72 个参数化器件族（耦合器、功分器、滤波器、天线、过渡
  结构……）。每个模板先用闭式物理公式综合出初始尺寸，并注册该器件族的验收
  判据，让你分得清"真结果"和"网格假象"。
- **优化闭环** —— TPE、CMA-ES、NSGA-II 多目标；还有代理模型路线：先用一批
  仿真结果拟合一个便宜的模型，然后在模型上搜索，省掉大部分昂贵求解。批量
  战役无人值守运行，带预算准入、配额和看门狗。
- **处处有质检门** —— 能量守恒与无源性检查、网格伪象诊断、跨引擎仲裁（同一
  几何拿到第二个求解器上对照）、物理不变量测试。没过门的结果如实报 FAIL，
  绝不静默放行。
- **AI 能指挥，但不许编数** —— 完整的 MCP 服务器，Claude Desktop、Cursor 或
  你自己的 agent 都能操作框架。agent 的修改先进沙箱草稿、过验证门，才允许
  碰你的工作区。

新增能力：面向平面器件族的 **EDB 快车道** —— 声明式发射器用闭式物理内核
综合出版图 spec，每个求解点只起一个短命 `ansysedt -BatchSolve` 进程（不
存在可被毒化的长驻桌面会话），第二段 `-batchextract` 导出 Touchstone，
每件产物过七因子健康门才能进数据集。同期落地：从原始标准件测量反解二端
口误差箱的 **TRL/SOLT 校准内核**，以及把整条链从单一入口驱动的 HFSS 一次
性批处理基座。

![工作流](docs/assets/zh/workflow.png)

（本图内嵌数字为历史快照，口径见上方架构图处的注记。）

## 信任层

我们最看重的部分：怎么判断一个仿真结果*可信*？rfauto 把它做成一等公民——
每次运行都有健康门体检，每个模板有参考响应锚点，每个数字出自确定性内核，
AI 想改任何东西都要走沙箱加三道门。

![信任层](docs/assets/zh/trust_layer.png)

## 快速开始

**环境要求：** Python 3.10–3.12（`python --version` 确认）。不需要任何商业
工具——内置 fake 求解器覆盖全部核心功能。下面六步：安装 → 体检 → 零
license 冒烟 → 看 run 产物 → 起工作台 → 真机。

### 1. 安装

```bash
git clone https://github.com/geer1895/rfauto && cd rfauto
python -m venv .venv
.venv\Scripts\activate               # Linux/macOS: source .venv/bin/activate
pip install -e ".[ui]"               # 核心 + 浏览器工作台
```

`rfauto --help` 出命令表即装好。只装核心（`pip install -e .`）够跑第 2-4
步；`rfauto ui` 需要 `[ui]` 组（starlette/uvicorn，缺装时该命令报
ImportError）。

### 2. 体检（秒级）

```bash
rfauto doctor
```

打印本机探到的 Python/AEDT/ADS 版本与路径。AEDT 读安装目录推断版本，标
`best_effort`，不冒充 verified；ADS 经实测握手才标 `verified`。
`rfauto doctor --janitor --min-free-gb 8` 加查残留进程面板（孤儿
`ansysedt` 清点 + AEDT 工程锁）与内存闸。

### 3. 第一条链路，零 license

```bash
$ rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
✓ 仿真完成  run_id: 20260921_001708_3fe788d3
  指标:
    s11_db_max_in_band: -12.21
```

fake 是闭式解析近似模型，不是电磁仿真——它的用处是把「配方 → run → 产物
→ 质检门」整条链路在几秒内走通，不占 license。真物理在第 6 步切 openEMS
或 HFSS，配方与质量门不变。

### 4. 看 run 产物

每次 run 落在 `runs/<时间戳>_<哈希>/`：

- `meta.json` —— 环境指纹（git sha、numpy/BLAS、pip freeze 哈希），复现凭据
- `recipe.snapshot.yaml` —— 本次 run 的配方快照，`rfauto replay <run_id>`
  按它复跑
- `report.md` 与 `results/` —— 指标与图；真机 run 另有 Touchstone 文件

产物新鲜度校验（manifest 收官指纹 vs 盘上文件；三态 fresh/stale/legacy）：

```bash
rfauto runs verify <run_id>
```

`stale`——旧文件顶替新 run——退出码 1，不静默放行。

### 5. 起工作台

```bash
rfauto ui --port 8643        # 缺省 8642；被旧实例占用时换端口
```

浏览器打开 http://127.0.0.1:8643（仅本机）。**Runs** —— 每次 run 的指标、
曲线与质量门判定。**模板画廊** —— 72 种器件模板，每张卡可点开白话参数表
（是什么、数值什么含义、怎么算出来的）。**优化调参** —— 第 3 步同款循环
搬进浏览器：通道保持 **fake**，点「启动」——Wilkinson 功分器 10 轮几秒跑
完，出推荐尺寸结果卡。**Tools** —— 323 个闭式计算器，随手交叉核对。右上
角 **zh/EN** 整站切换。

习惯终端的话，不开浏览器也行——闭式综合器随手一例：

```bash
$ rfauto syn mline 50.0 --freq 2.4 --stackup rogers4350b_h0.508
微带线综合结果 (rogers4350b_h0.508 @ 2.4 GHz)
  目标阻抗: 50.00 Ω
  线宽:     1.1133 mm
  εeff:     2.8530
```

### 6. 真机

```bash
pip install -e ".[hfss]"     # pyaedt；需 AEDT 2025 R1
```

把通道切到 **openEMS**（免费，编译指引见文档）或 **HFSS**——配方与质量门
不变。无人值守跑 HFSS 前先读
[docs/unattended_hfss_automation.md](docs/unattended_hfss_automation.md)
——一年真机踩坑沉淀的操作纪律。最先咬人的三条：

- `Desktop(version=…, non_graphical=…, new_desktop=…)` —— 构造参数名不是
  旧版 `specified_version`；
- 同一 Desktop 只建一个 `Hfss` 实例——第二个实例的设计变量管理器开始返
  `None`；
- 一次失败赋值毒化整个会话（元数据查询返 `None`），gRPC 通道连带损坏，
  `release_desktop` 随之静默失败——毒化会话整轮重建，绝不带毒续跑。

发射前闸门：`rfauto doctor --janitor --min-free-gb 8`；工程/outdir/日志
一律绝对路径——相对 `-outdir` 会让 `Project.Rename` 挂起数分钟才报错。跑
测试套件：`pip install -e ".[dev]"` 后 `python -m pytest tests/unit -q`。
想用容器：[Docker 容器](#docker-容器)两条命令——镜像只含开源核心（fake
求解器与确定性计算器），不含商业工具。

![命令行实操（真实输出）](docs/assets/cli_demo.png)

### 常见第一次

| 症状 | 可能原因 | 处置 |
|---|---|---|
| `rfauto ui` 打不开或页面 404 | 8642 被旧实例占着（旧进程带旧代码） | `rfauto ui --port 8643`；或核对命令行后清掉旧实例 |
| AEDT 写文件失败（STEP/导出） | 路径含中文等非 ASCII 字符 | 工程/工作目录用 ASCII 路径；先落 ASCII 临时目录再拷回 |
| HFSS 连不上/报 license 错 | 孤儿 `ansysedt` 进程占着许可席位 | `rfauto doctor --janitor` 出清单（带父进程链证据），复核后 `--janitor-clean` |
| 求解中途被杀/机器卡死 | 可用内存不足 | 发射前 `rfauto doctor --min-free-gb 8 --enforce`，低于阈值非 0 退出 |
| license 服务器连不上 | 探测目标未配置 | 设 `RFAUTO_LICENSE_SERVER` 后重跑 `rfauto doctor` |
| fake 结果与真机差很多 | fake 是闭式解析近似，不是电磁仿真 | fake 只验链路；通道切 openEMS/HFSS——同配方同质量门 |
| run 目录里没有 Touchstone | fake 通道只出解析指标 | 看 `results/metrics.json`；Touchstone 出自真机通道 |
| 盘上 Touchstone 和 run 记录对不上 | 旧文件顶替了新文件 | `rfauto runs verify <run_id>`——stale 退出码 1，不静默放行 |

接下来就是常规循环：

```bash
rfauto sweep recipes/wilkinson_pd_v1.yaml --adapter fake   # 参数扫描
rfauto tune  recipes/wilkinson_pd_v1.yaml --max-trials 60  # 优化外环
rfauto replay <run_id>                                     # 复现历史 run
```

### 连接 AI 助手（可选）

```bash
pip install -e ".[mcp]"
python -m rfauto.mcp_server        # stdio 传输；152 个工具
```

在 MCP 客户端里注册（Claude Desktop 示例）：

```json
{
  "mcpServers": {
    "rfauto": {
      "command": "python",
      "args": ["-m", "rfauto.mcp_server"],
      "cwd": "/path/to/rfauto"
    }
  }
}
```

## Docker 容器

仓库根目录自带 `Dockerfile`，CI 每次 push 或 PR 都会构建并在容器里冒烟。
本机两条命令即可复验：

```bash
docker build -t rfauto:local .
docker run --rm rfauto:local   # 入口冒烟：打印 CLI 帮助后正常退出
```

镜像只含开源核心——不含任何商业工具与许可。真跑时挂载工作目录即可：
在镜像名前加 `-v "$PWD:/work" -w /work`。

## Web UI

`rfauto ui` 会启动一个本地核验工作台——数据不出你的机器。查看每次 run 的
指标与曲线、对比适配器、使用内置微波计算器，AI 代理的修改提案也在这里
先审后生效：

```bash
rfauto ui          # http://127.0.0.1:8642 — 仅本机
```

| | |
|---|---|
| ![总览](docs/assets/ui_dashboard.png) | ![S 参数分析](docs/assets/ui_sparams.png) |
| ![远场方向图](docs/assets/ui_farfield.png) | ![模板画廊](docs/assets/ui_gallery.png) |

每个页面都支持深链接（`#runs`、`#sparams`、`#tools`…），可以收藏常用视图。

### 为什么可以信这些结果？

每个仿真结果都带出处：哪个求解器跑的、几何怎么推导的、过了哪些质量门。
79 个标定锚——每个都在 HFSS（参考基准）和 openEMS（免费）之间做了交叉
验证——覆盖整个模板库。画廊里每个经过双引擎仲裁的模板都有认证徽章。
两个引擎对同一物理结构给出一致预测时，你可以放心用免费的那个做扫参。

## 引擎

| 引擎 | 许可 | 典型角色 |
|---|---|---|
| HFSS（Ansys AEDT） | 商业 | 全波参考 / 仲裁基准 |
| ADS（Keysight） | 商业 | 电路与系统联合仿真 |
| openEMS | 开源（GPL，子进程运行） | 快速 FDTD 批量求解 |
| COMSOL | 商业 | FEM 多物理场 |
| Elmer | 开源 | 多物理场 FEM |
| NGSolve | 开源 | 频域 FEM |
| Meep | 开源 | FDTD（Linux） |
| Icepak / Q3D（Ansys） | 商业 | 热仿真 / 场提取 |
| Palace | 开源 | 并行 FEM |
| KiCad | 开源 | PCB DRC 与版图提取（子进程） |
| ngspice | 开源 | 电路仿真 |
| FDTDX（JAX） | 开源 | 可微 FDTD |

商业工具需要你自持合法许可；框架既不附带也不规避任何许可，本仓库不分发任何
厂商专有内容（见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)）。

## 文档

- [模板参考](docs/rf_template_references.md) —— 逐模板验收值与建模规则
- [openEMS 构建指南](docs/openems_build_guide.md)
- [COMSOL 备注](docs/comsol_references.md) · [迁移指南](docs/migration_guide.md)
- [模板元数据](docs/templates/) —— 每个器件族一份 `meta.yaml`
- [更新日志](CHANGELOG.md) · [参与贡献](CONTRIBUTING.md)

## 现状与路线图

rfauto 是能跑的工具，不是演示：核心链路（模板 → 综合 → 求解 → 质检门 →
优化 → 报告）在真实的 HFSS、ADS、openEMS、COMSOL、KiCad 安装上运行，背后是
上面那个规模的测试套件。目前以 Windows 为主、单人维护，正在改善
Linux/Docker 支持。

接下来计划在公开仓里推进的事：

- **数据集与评测基准** —— 内置数据工厂管线积累的仿真数据集、agent 评测集
  暂不随本仓发布；我们计划逐步公开，非常欢迎协作者一起建设与整理；
- **方法学论文** —— 质检门/确定性内核方法学的论文在计划中，欢迎参与与共同
  撰写；
- **更多器件族、更多引擎、更好的上手体验** —— 都是好的第一个 issue。

如果这些方向你感兴趣，欢迎开 issue——我们希望这是一个社区项目，而不是一个
人的存档。

## 参与贡献

欢迎 issue 和 PR——快速上手、贡献约定、代码注释里 `#NNN` 标记的含义见
[CONTRIBUTING.md](CONTRIBUTING.md)。

## 引用

如果 rfauto 对你的研究有帮助，欢迎引用——见
[CITATION.cff](CITATION.cff)。

## 许可证

rfauto 采用 **GPL-3.0**（见 [LICENSE](LICENSE)）。第三方依赖许可证清单见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。可选的 openEMS 适配器通过
独立子进程驱动 GPL 的 openEMS；本仓库不包含 openEMS 绑定本体，由用户从
openEMS 官方源码自行编译。
