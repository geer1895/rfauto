<!-- PR-10 文档站同步副本：源=docs/tutorials/skill-packages.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# SKILL 能力包：把 rfauto 能力装进 AI 代理

> `skills/` 目录下的每个 `rfauto-*` 包是一个 **agentskills.io 规范的
> SKILL.md 能力包**——AI 代理（Claude Code 等）按需装载后，获得"该问哪个
> 命令、怎么读 JSON 信封、何时结果不可信"的编排知识；包内所有物理数字
> 都逐字来自 rfauto 确定性卡与内核实跑记录，**代理自己不产生任何数字**
>（rfauto 铁律 7）。本教程讲三件事：三语义互链（能力卡/内核卡/SKILL 包）、
> 安装（Claude Code 用户级目录拷贝形态）、再生产线（`card_to_skill`，同
> 入参逐字节幂等）。前置：`docs/tutorials/getting-started.md`（会跑通一条
> 仿真链）。英文版（English version）：
> `docs/tutorials/skill-packages_en.md`。

## 0. 你将完成

1. 分清三份机读资产各管什么：capability card（怎么跑）/ kernel card
   （怎么算）/ SKILL 包（代理怎么用），以及它们如何逐字节互链；
2. 把一个包安装进 Claude Code（用户级或项目级）并知道它何时被触发；
3. 看懂包内三层渐进披露结构（SKILL.md 快读 → references/ 细节 →
   scripts/ 核验）；
4. 会用 `card_to_skill` / `card_to_skill_batch` 从卡再生一个包（幂等，
   再生门逐字节钉）。

## 1. 三语义互链：能力卡 / 内核卡 / SKILL 包

rfauto 的机器可读能力面由三种资产承载，**同一张卡 ID 三层递进**：

| 资产 | 位置 | 回答的问题 | 典型内容 |
|---|---|---|---|
| capability card（能力卡） | `docs/capability_cards/<id>.md` | 这个模板**怎么跑** | 适用场景 / 名义参数 / 敏感性排序 / 判据 / 引擎精度锚 / 失败模式坑账链 |
| kernel card（内核卡） | `docs_site/kernel_cards/<k>.md` | 数字**怎么算** | 公式 LaTeX + docstring 逐字引文钉 / 精度域 / 代码入口 / 锚 / 测试面 |
| SKILL 包 | `skills/rfauto-<slug>/` | 代理**怎么用** | agentskills.io frontmatter（触发条件）+ 渐进披露正文 + 两卡逐字节副本 + 核验脚本 |

互链方向（单向、可验证）：

```text
rfauto 内核（core 纯函数）
   └─► capability card / kernel card（生成器产出，再生门逐字节保鲜）
          └─► SKILL 包 references/（两卡逐字节副本，card_to_skill 再生门）
                 └─► SKILL.md 正文（数字逐字引自卡；无任何新数值）
```

因此从 SKILL 包里的任何数字出发，都能沿"包 → 卡 → 内核/锚"追到确定性
出处；反向不成立——改卡不改包，再生门测试当场红（这正是门的作用）。

## 2. 安装（Claude Code 用户级拷贝形态）

SKILL 包是**纯目录**（无构建步骤）：把包目录整体拷进 Claude Code 的
skills 搜索路径即可。

用户级（对该机器所有项目生效）：

```bash
# Git Bash / Linux / macOS
mkdir -p ~/.claude/skills
cp -r skills/rfauto-mline-synthesis ~/.claude/skills/
```

```powershell
# Windows PowerShell（用户级目录 = %USERPROFILE%\.claude\skills）
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse skills\rfauto-mline-synthesis "$env:USERPROFILE\.claude\skills\"
```

项目级（只对该项目生效，可随仓共享）：

```bash
mkdir -p <project>/.claude/skills
cp -r skills/rfauto-mline-synthesis <project>/.claude/skills/
```

安装后无需注册——Claude Code 读取每个包 frontmatter 的 `description`
（触发条件 + 触发词，中英并列）决定何时加载该包。例如装有
`rfauto-mline-synthesis` 时，问"50 ohm line width on Rogers 4350B"或
"微带线 50 欧姆线宽"即命中；问 CPW/带状线则不命中（description 里的
负触发条款明确排除了同族其他卡）。

## 3. 包内容解剖（以 rfauto-mline-synthesis 为例）

```text
skills/rfauto-mline-synthesis/
├── SKILL.md                 # frontmatter + 快读正文（<500 行预算）
├── LICENSE.txt              # 公开仓许可副本
├── references/
│   ├── capability_card.md   # = docs/capability_cards/mline.md 逐字节副本
│   ├── kernel_card.md       # = docs_site/kernel_cards/mline.md 逐字节副本
│   └── pitfalls.md          # 坑账链单独抽出（症状→坑号→处置）
├── scripts/
│   └── verify_output.py     # 结构性核验器（零物理断言）
└── assets/
    └── stackups.yaml        # configs/materials.yaml 本卡层叠键只读子集
```

三层渐进披露：

1. **SKILL.md（快读层，触发即读）**——frontmatter 合规三钉：
   `name` = `rfauto-<slug>` 且等于目录名（`^[a-z0-9][a-z0-9-]*$`）；
   `description` ≤1024 字符、只写触发与负触发、零流程词；私有键全部收进
   `metadata`（作者/版本/来源卡/生成器），顶层不放客户端方言键。正文给出
   "何时适用 → 键命令 → 怎么读 JSON 信封 → 已知边界 → 何时开 references"。
2. **references/（细节层，按需加载）**——两卡逐字节副本（再生门逐字节
   比对）+ 坑账链抽出件；SKILL.md 内给"何时打开哪个文件"的加载时机表。
3. **scripts/verify_output.py（核验层）**——对保存的内核 JSON 输出做
   结构性核验（JSON 可解析、无 NaN/Infinity、`--expect KEY=VALUE` 数值
   互检）。它**不做任何物理断言**：传入的期望值必须来自内核输出或卡面。

```bash
# 例：对一次 syn mline 实跑产物做核验（期望值 = 内核自己报的数）
rfauto syn mline 50 --freq 2.4 --stackup rogers4350b_h0.508 --json > run.json
python scripts/verify_output.py --json run.json --expect width_mm=1.1133
```

## 4. 内置包清单

| 包 | 来源卡（capability + kernel） | 一句话 |
|---|---|---|
| `rfauto-mline-synthesis` | mline（两卡齐） | 微带线综合：宽↔阻抗↔εeff，含内核实跑记录与 JSON 信封判读表 |
| `rfauto-cpw` | cpw（两卡齐） | 共面波导族能力包（产线直转样例） |
| `rfauto-pifa` | pifa（单能力卡） | PIFA 天线族能力包（产线直转样例） |
| `rfauto-wilkinson-power-divider` | wilkinson（两卡齐）+ 配方 | 威尔金森功分器 run/tune/autotune 工作流（recipe 型，刷新版 frontmatter） |
| `rfauto-branchline-coupler` | branchline（两卡齐）+ 配方 | 分支线电桥工作流（recipe 型） |
| `rfauto-patch-antenna` | patch（两卡齐）+ 配方 | 矩形贴片天线工作流（recipe 型） |

两类包的差别：`card_to_skill` 产线包（前三）从卡全自动生成；recipe 型包
（后三）正文由 `recipe_to_skill` 从 `recipes/*.yaml` 生成（历史包按
agentskills.io 规范刷新：frontmatter 合规 + 渐进披露对齐 + references
副本），两者共享同一 frontmatter 合规口径，由同一测试门钉住。

## 5. 再生产线（card_to_skill，确定性、幂等）

产线在 service 层（零新 CLI 叶/零 MCP 工具——卡到包是文档变换，不是
新命令面）：

```python
from rfauto.service.skill_service import (
    card_to_skill,        # 卡 → 包文件映射（纯构造，零 IO）
    write_card_skill,     # + 落盘（output_dir 必填）
    card_to_skill_batch,  # 批量：全部 75 张模板能力卡一次产线直转
)
```

确定性口径：

- 内容逐字取自卡文件 / 调用方记录的内核实跑 JSON / 显式入参——**产线
  自身零计算、零新数值**（铁律 7）；
- 同入参两次生成**逐字节相同**（`tests/unit/test_card_to_skill.py`
  逐字节比对再生门，与 kernel 卡保鲜门同口径）；
- 仓库锚（卡目录/materials.yaml/LICENSE）由 `__file__` 推导，与调用方
  cwd 无关；`write_card_skill` 的 `output_dir` 必填——不设 cwd 相对
  缺省（#144 缺省目录纪律，防止包被静默写进真实工作区目录）；
- frontmatter 违规（name 不合规 / description 超 1024 或含流程词 /
  正文超 500 行 / 层叠键不存在）一律报错信封，不静默降级。

## 6. 边界与纪律

- **数字纪律**：SKILL 包内数字只从确定性源读出（卡/内核实跑记录）；
  包不含任何"典型值""经验值"。代理引用包内数字时必须能指回
  `references/` 里的卡面原文。
- **FAIL 如实**：`verify_output.py` 判 FAIL 就是 FAIL，不重试凑绿
  （#122）。
- **评测包（evals/）**：R9 §8.3 规格中的评测骨架（trigger eval 等）
  暂未随包出货，当前交付面 = SKILL.md + references/ + scripts/
  （+assets/），评测包留待后续批次。
- **发布口径**：包随公开仓分发（拷贝形态安装），push 与版本发布由
  用户指令驱动，AI 不自行发布。
