# MCP 实战：把 rfauto 接进 AI 客户端

> 写给想用 Claude Desktop / Cursor 等 MCP 客户端驱动 rfauto 的你。文中
> 的入口名、启动行为、工具与资源数量、全部调用输出均为当前工作区实测
> （`pyproject [project.scripts]`、`scripts/check_numbers.py`、stdio 钉
> 测试与只读工具实调）；mutating 工具只讲不调。读完你将知道：怎么启动、
> 客户端怎么配、152 个工具按域怎么找、典型调用长什么样、它和 CLI 是
> 什么关系。
> 英文版（English version）：docs/tutorials/mcp_in_practice_en.md
> （2026-10-19 全量复测同笔）。

## 0. 前置

- 已按 docs/tutorials/getting-started.md 装好环境（`.venv` +
  `pip install -e .`）；MCP 传输依赖在 extras 里：`pip install -e ".[mcp]"`
  （fastmcp>=3.0.0，当前 venv 实测 3.4.7）。
- 工作目录在仓库根（MCP 工具里的 `runs/`、`recipes/`、`runs/datasets/`
  都是相对服务进程 cwd 解析的——客户端配置里的 `cwd` 就是干这个的）。

## 1. 启动：rfauto-mcp（stdio 传输）

MCP 服务器是独立的 console script（pyproject `[project.scripts]` 注册：
`rfauto-mcp = "rfauto.mcp_server:main"`）：

```bash
.venv/Scripts/rfauto-mcp.exe
```

它是**零参数、零 stdout** 的入口：stdio 传输把 stdout 当 JSON-RPC 协议
信道，任何多余打印都会污染帧——所以这个命令没有 `--help`，启动横幅走
stderr。实测（stdin 接 /dev/null，服务器即启即退）：

```
$ .venv/Scripts/rfauto-mcp.exe < /dev/null > out.bin 2> err.txt
$ echo $?
0
$ wc -c < out.bin
0
$ cat err.txt            （节选；原样含 FastMCP 横幅框线）
    FastMCP 3.4.7
    🖥  Server:      rfauto, 3.4.7
[10/12/26 01:18:15] INFO     Starting MCP server 'rfauto' with
                             transport 'stdio'
```

（节选；stdout 恰 0 字节是发布级回归钉——#278。）

同源入口：`python -m rfauto.mcp_server`（模块带 `__main__` guard，README
配置样例用的就是它）。注意区分：`python -m rfauto`（CLI 包）不是有效
入口，CLI 一律走 `rfauto` 命令；MCP 两个入口随便选，同一份代码。

## 2. 客户端接入

Claude Desktop 的 `claude_desktop_config.json` 样例（推荐 console script
形态；Windows 路径转义用 `\\`）：

```json
{
  "mcpServers": {
    "rfauto": {
      "command": "D:\rf_workspace\\.venv\\Scripts\\rfauto-mcp.exe",
      "cwd": "D:\rf_workspace"
    }
  }
}
```

通用 stdio JSON 形态（README 同款，模块入口版）：

```json
{
  "mcpServers": {
    "rfauto": {
      "command": "python",
      "args": ["-m", "rfauto.mcp_server"],
      "cwd": "D:\rf_workspace"
    }
  }
}
```

两种形态同一实现，`cwd` 都指向仓库根。**具体字段名（mcpServers、
command/args/env）以你的客户端文档为准**——各家客户端对配置文件位置与
schema 细节略有差异，上面只保证服务侧正确。

排查顺序：客户端报连不上 → 先在终端裸跑 §1 的命令确认 stderr 横幅出现
→ 再查客户端日志里 JSON-RPC 握手。**stdout 必须纯协议**：给入口包一层
打印 banner 的 shim 必炸。

## 3. 面览：152 个工具 + 9 个 resources

数量口径：`scripts/check_numbers.py` 实测输出 `MCP=152+9res`（工具=
facade + `mcp_tools/` 全部模块的 `@mcp.tool` 注册面正则计数；resources=
注册面 `list_resources()` 实枚举）。README 规模行同口径（152+9）；
docs_site 机生 reference 页同源新鲜。**docs/reference.md 的"当前 100 个
工具（2026-09-24）"已过时**，以 check_numbers 为准。

工具按域拆在 `src/rfauto/mcp_tools/` 的 39 个模块里，按功能归组如下
（括号=该组工具数，各组的代表工具名字面照录注册面）：

| 组 | 模块（数） | 一句话 |
|---|---|---|
| 入门与任务编排（21） | basic(3) jobs(6) ops(3) db(6) preflight(1) remote(2) | doctor 环境体检、create_run/create_run_async/poll_job/wait_job 任务链、db_* 注册表数据库、remote_* 远程探活 |
| run 检视与诊断（14） | runs(7) diagnose(4) explain(3) | get_metrics/get_run_artifacts/compare_runs/run_monitor、cm_diagnose_q 耦合矩阵诊断、explain_run 失败指纹解释 |
| 闭式综合与器件设计（19） | synth(6) slotline(5) mmt(2) metasurface(2) adc(2) afs_interop(2) | synthesize/synthesize_bpf 综合、槽线/Marchand、SIW 模基、超表面、ADC 杂散 |
| 模板规格/战役/EDB（14） | specs_campaign(7) edb(3) certify(4) | plan_campaign/run_campaign 战役状态机、edb_build_solve 快车道、certify_design 公差证书 |
| Agent 提案与知识（19） | agent(6) agent2(3) optim(2) anchors(2) knowledge(1) guidelines(1) rationale(4) | rf_propose_params→三层 Gate 提案链、start_tune/run_sweep、锚注册表、RAG 检索 |
| 数据集（8） | datasets(4) datasets_ops(4) | list_datasets/query_dataset 只读查询、import_workdir_runs/dataset_set_visibility 等 |
| 频段/环境/老化（21） | bands(10) env_reliability(8) aging(3) | bands_* 标准频段注册表、湿度/MSL/玻纤 skew/低温、aging_* 寿命失谐 |
| SI/PI/EMC/测量（20） | si_lake(4) pdn(3) emc(4) nfmeas(6) vna(3) | si_channel_report、pdn_analyze、emc_cispr_*、近场/NFC/SAR、VNA 回放 |
| 多物理场/远场/版图（7） | multiphysics(3) farfield_kicad(4) | electrothermal_chain 电热链、farfield_view/kicad_extract |
| UQ/报告/评测（9） | uq(5) report_bench(4) | uq_yield_at 良率、goldset_regression/agentbench_regression 回归门、export_report_pdf |

9 个 resources（只读，URI 照录注册面）：

| URI | 内容 |
|---|---|
| `rfauto://runs/index` | runs 索引（注册表最近 20 条，同 run_store.list_runs） |
| `rfauto://knowledge/materials` | 材料库（configs/materials.yaml 原文结构） |
| `rfauto://knowledge/compat_matrix` | 版本兼容矩阵 |
| `rfauto://knowledge/terminology` | 术语卡 |
| `rfauto://toolsets/definition` | 工具集目录（每条目 name/description/skill/tools） |
| `rfauto://edb/status` | EDB 快车道状态（五族能力 + 产物根资产统计） |
| `rfauto://edb/datasets` | runs/datasets/ 下 edb_lane_* 数据集清单 |

客户端里的读法：先 `list_tools` 看名字与描述（fastmcp 直接用 pydantic
生成的 JSON Schema 当 input schema），拿不准副作用就先读工具 docstring
——**mutating 工具必须显式描述副作用**是本服务器的设计红线，另外还有
两条：不提供 delete 类破坏性工具；所有工具返回 `{ok, data|error}` 信封。

## 4. 典型调用走读（只读工具，实调实录）

下面四例全部是当前工作区实调记录（走 fastmcp 的 `call_tool` 注册面，
等价于客户端里的一次工具调用）。**mutating 类（create_run/start_tune/
run_campaign 等）本文只讲不调**——它们会真起仿真/真写盘。

### 4.1 doctor：环境体检

入参 `{}`。返回信封（structured content 摘录）：

```json
{"ok": true, "checks": [
  {"name": "Python", "status": "ok", "detail": "3.12.14"},
  {"name": "AEDT", "status": "ok",
   "detail": "<hfss-install-dir>（版本 2025.1，best_effort）"},
  {"name": "ADS", "status": "ok",
   "detail": "<ads-install-dir>（版本 2027，verified）"},
  {"name": "缓存模式", "status": "ok", "detail": "readwrite"}]}
```

接上新客户端先调这个：一眼看清求解器/license/路径状态，等价 CLI
`rfauto doctor`。

### 4.2 query_dataset：数据集行级查询

先 `list_datasets`（缺省扫 runs/datasets/，实测当前注册表 20 个数据集），
再查其一（`columns` 列裁剪、`limit` 行上限；返回节选，略去 offset/
order/filters 等分页键）：

```json
{"ok": true, "dataset": "edb_lane_w1_smoke_20261009",
 "rows": [
  {"run_id": "branchline", "model": "edb_branchline",
   "adapter": "hfss", "cost": null},
  {"run_id": "power_divider", "model": "edb_power_divider",
   "adapter": "hfss", "cost": null}],
 "n_rows": 2, "total_rows": 2, "columns": ["run_id", "model",
 "adapter", "cost"], "limit": 5}
```

读法：`where` 是单条 SQL WHERE 片段（白名单校验，防注入），`model`/
`study_name` 走参数绑定；**`n_rows` 是本页返回行数，`total_rows` 才是
过滤后全量**（`limit=1` 时 n_rows=1、total_rows=2，实测核对过——拿
n_rows 当总数会犯 #369）。数据集面详见
docs/tutorials/datasets_and_health_gates.md。

### 4.3 run_calculator：闭式计算器

物理数字只出自确定性内核（LLM 永不产生物理数字），计算器是 agent 拿数
的正道。微带综合一例：

```json
{"ok": true, "calculator": "microstrip_synthesis",
 "params": {"z0_ohm": 50, "freq_ghz": 2.4, "epsilon_r": 3.66,
            "h_mm": 0.508},
 "result": {"width_mm": 1.1117, "z0_actual_ohm": 50.0,
            "eps_eff": 2.8579, "status": "ok",
            "lambda_g_mm": 73.891},
 "experimental": false}
```

名单先 `list_calculators` 查（**2026-10-19 复测 261 条 = 260 常规 +
1 实验键**——本文初稿时点的 178 条已随内核扩批过期，见文末核对清单
滚动声明；实验键标 `experimental: true` 缺省拒跑，`allow_experimental`
三态显式放行）。同一内核的另两个壳：CLI `rfauto calc run`、UI「微波
工具箱」页。

### 4.4 get_metrics：run 指标读取

入参 `run_id`（runs/ 目录名）。注意这个工具的信封是 `{ok, data}` 形态
（payload 套在 data 里，逐工具以 schema 为准）：

```json
{"ok": true, "data": {"metrics": {
  "s11_db_max_in_band": -17.838412525712467,
  "s11_db_min_in_band": -18.033298403947782,
  "s21_db_mean_in_band": -0.1606843735240625,
  "eps_eff_beta_mean_in_band": 2.7686197083011397}}}
```

（自真实 openEMS run 节选——原返回还有 zl/eps_eff 等键与一个 `notes`
字段，随行解释 eps_eff 两种口径的参考面语义，读指标先读 notes。）

长仿真走异步链：`create_run_async` 返回 job_id → `poll_job`/`wait_job`
轮询 → `get_metrics` 读数；这份任务状态是持久化的，CLI
`rfauto jobs status <job_id>` 读到的是同一份（同一 SQLite 索引）。

## 5. 与 CLI / UI 的关系：同 service 单源

三壳共享同一 service 层——工具不是 CLI 的复刻，也不是各写各的。实测
一例：CLI `rfauto datasets query` 与 MCP `query_dataset` 的函数体都收敛
到 `service.dataset_service.query_dataset`（读 `cli/domains/surrogate.py`
与 `mcp_tools/datasets.py` 可逐行核对）。含义：

- 语义修正/门禁收紧只改 service 一处，CLI 与 MCP 同时生效；
- 教程里 CLI 的读法（--help、旗标表）对 MCP 工具参数同样适用，反之
  亦然；
- 审计同源：`rfauto chat --channel mcp` 可以在本仓内直接用 MCP 客户端
  通道对话（默认 service 直调通道），两路同审计（audit.jsonl）。

agent 自主改配方走沙箱草稿 → 三层 Gate → promote，不走工作区直写
（`rfauto sandbox`/`inbox` 同一面）；对话里没配 API key 时是纯指令模式，
不会半途真打外网。

## 6. 下一步

- 数据集行级语义与健康门判读：docs/tutorials/datasets_and_health_gates.md
- 从安装到第一次 fake run：docs/tutorials/getting-started.md
- 全部 CLI 命令与模块的权威出处：docs/reference.md（注意其 MCP 计数
  节已过时，见 §3）
- 配方→调参→复现闭环（MCP 里对应 create_run/start_tune 的语义同款）：
  docs/tutorials/first_optimization_loop.md

## 附：本文核对清单

| 项 | 核对方式 | 结果 |
|---|---|---|
| `rfauto-mcp` 入口名 | pyproject `[project.scripts]` 实读 | 过（rfauto-mcp = "rfauto.mcp_server:main"） |
| 零参数零 stdout | `rfauto-mcp.exe < /dev/null` 实跑 | 过（exit 0，stdout 0 字节，stderr 横幅 transport 'stdio'） |
| 同源入口 `python -m rfauto.mcp_server` | 同款钉测实跑 | 过（exit 0，stdout 0 字节） |
| fastmcp 版本 | `python -c "import fastmcp"` 实跑 | 过（3.4.7） |
| extras 声明 `.[mcp]` | pyproject 实读 | 过（fastmcp>=3.0.0） |
| MCP=152+9res | `scripts/check_numbers.py` 实跑 | 过（工具=注册面正则 152；resources=list_resources()=9；2026-10-14 +2 资源） |
| 工具按域分组表 | `^@mcp\.tool` 逐模块锚定正则实测 | 过（39 模块，十组合计 152） |
| doctor/list_datasets/query_dataset/run_calculator/get_metrics | 只读工具实调 | 过（§4 输出均为实调 structured content 摘录） |
| n_rows vs total_rows | query_dataset limit=1 实调 | 过（n_rows=1，total_rows=2） |
| list_calculators=320（含 1 实验键；2026-10-20 架构批 复测，306=305+1 系 架构批 收官时点已随第五梯队 +13 过期） | 只读工具实调 | 过（319 常规+1 实验，与 check_numbers CALCULATOR_REGISTRY=319（含实验键 320）口径一致；本行随内核扩批滚动，以 rfauto calc list 实时为准） |
| CLI/MCP 同 service 单源 | `cli/domains/surrogate.py`/`mcp_tools/datasets.py` 源码实读 | 过（两路收敛 service.dataset_service.query_dataset） |
| 客户端配置样例 | 与 README「MCP Agent 接口」节同源核对 | 过（"以你的客户端文档为准"已标注） |
