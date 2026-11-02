<!-- PR-10 文档站同步副本：源=docs/explanation/cli-json-channel.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 解释：CLI rich 人读 / JSON 机器读的信道分域

> 这是一篇 explanation（解释文）：回答"为什么每条 CLI 叶都要带 `--json`、
> 为什么失败路径在 `--json` 下不许吐红字裸文本、这套分域靠什么不退化"。
> 规范面（契约条款原文）：docs/envelope_contract.md；本文讲分域的
> 设计理由与守卫地图。文中全部符号/数字经 grep/实测复核（#222 家法，
> 复测时点 2026-11-01）。

## 问题：一个命令、两类消费方、两套失败表达

rfauto 的 CLI 同时服务两类消费方：终端前的人（看表格、看颜色、看
"下一步"提示）和管道/agent/脚本（拿可解析的 JSON 信封做分支判断）。
同一条命令的失败，对人说应该是"红字 + 可行动建议"，对机器说应该是
`ok=false` 的结构化信封——两种表达都对，但**绝不能混**：红字混进
JSON 流会砸掉解析器，JSON 混进人读输出会变成视觉噪音。

分域原则因此只有两条：

- **人读信道**（rich）：表格、红字、颜色、建议提示——注意力只花在
  需要人的事上。失败红字 + did-you-mean/坑号提示；成功路径的渲染由
  各叶自定（表格/进度条/摘要），不进契约。
- **机器读信道**（JSON）：一律走信封契约三态（ok / error / skipped，
  见 docs/envelope_contract.md），分支判据只看 `ok` 布尔，失败信息读
  `errors` 列表。`--json` 下失败路径**不许非 JSON**（VI-5 W6-B 家法），
  exit 码保留语义（service 失败=1，usage 参数错=2）。

## 单源出口：`_emit` 双分支

分域不退化靠的是**出口单源**：两条信道在同一个函数里分叉，而不是
各叶各自发明。单源在 `src/rfauto/cli/domains/_core.py`：

- `_emit(result, fail_msg, *, json_output)`（约 147 行）——所有薄壳
  叶的共用出口。失败时双分支：`--json` 分支把 result 原样包成失败
  信封（errors/error 两者都缺时 fail_msg 兜底入 errors），经
  `_attach_error_hints` 挂 hints 后 `console.print_json` 直出，exit 1；
  human 分支红字 `✗ fail_msg` + 逐条 `- err` + 经
  `_print_error_hints_text` 附加"→ 建议"行，同样 exit 1。成功时仅
  `--json` 分支信封直出（人读成功渲染归各叶）。
- `_emit_usage_error(msg, *, json_output)`（约 169 行）——参数解析
  失败统一出口：`--json` 下走 `error_envelope(msg)` 信封 + exit 2，
  人类分支红字一行 + exit 2（#ge1㉙ 契约：usage 错也不许红字裸文本
  混进 JSON 流）。
- `_print_next_steps_stderr(errs)`（约 118 行）——给人看的补充指针
  走 **stderr**：stdout 是既有红字/JSON 信封的消费面（管道/agent
  解析），hints 分离到 stderr 不污染主通道。

hints 挂载本身是 best-effort（#105 纪律）：`_attach_error_hints` 惰性
导入 + try/except 全包裹，hint 生成失败绝不遮蔽原错误——观测面不得
成为业务主路径的故障点，宁无 hint 不阻塞。

## 提示的确定性来源

人读信道的"聪明"全部来自**确定性数据**，不来自模型：

- `src/rfauto/service/hint_rules.py` 的 `_HINT_RULES`——pattern /
  match / hint / refs / severity 五字段规则表叶，条目来自踩坑账本的
  真实错误指纹（如"网格欠分辨"→收紧 mesh_resolution_mm，refs 指回
  坑号）；severity 排序 error > warn > info，未命中空表如实返回
  （不编造提示）。
- `src/rfauto/service/error_hints_service.py`——纯映射层：匹配永远
  基于异常类型名 + 消息原文子串，零 I/O、零物理数字。这是硬规则 7
  （数值只在确定性内核）的对偶：**映射表也是确定性数据**，LLM/人不
  改判据。
- `src/rfauto/service/recipe_validation.py::did_you_mean`——近邻提示
  （模型名/adapter 名打错时给最接近的合法值），消费点：
  `service/api/run_core.py`（校验失败出口）、`service/fab_service.py`、
  `service/template_spec_service.py`、`service/template_golden_service.py`。

## 退化防线：四道棘轮与两道双检

约定靠自觉维持必然退化（历史上每个"手感顺手"的裸 dict 都是这么长
出来的），所以分域配了机械防线：

| 防线 | 位置 | 钉什么 |
|---|---|---|
| AST 构造器守卫 | `tests/unit/test_envelope_contract.py`（`_FROZEN_BARE_OK_RETURNS=510`、`_FROZEN_SINGULAR_ERROR=159`，2026-10-18 冻结值，只降不升） | service/mcp 面新增裸 `{"ok": ...}` 字面量与单数 error 形 |
| CLI 裸字面棘轮 | `tests/unit/test_cli_envelope_ratchet.py`（`RATCHET_CAP=9`；沿革 87→72→18→9，只降不升） | `src/rfauto/cli/` 下 `{"ok"` 字面出现次数 |
| `--json` 棘轮 | `tests/unit/test_w2_c_json_coverage.py`（`RATCHET_BATCH_A=110` → `RATCHET_BATCH_B=1`；`W6B_EXEMPT=["ui"]`） | 新 CLI 叶无 `--json` 旗标即红；缺旗标集合必须**恰好等于**豁免清单 |
| MCP 逐工具双检 | `tests/unit/test_mcp_tool_consistency.py`（#270 家法） | dis 逐指令 LOAD_GLOBAL 名字解析（抓 NameError 死壳）+ AST 函数体 import 目标 hasattr 双检 |
| MCP 计数钉 | `tests/unit/test_mcp_server.py`（`assert len(tools) == 166`，2026-11-01 实测；数字沿革留在测试行内注释） | 机器读信道工具面静默缺员 |

`--json` 棘轮是合流"新面必红清单"①的钉面：全树 292 条 CLI 叶
（`scripts/check_numbers.py` `count_cli()` 实测 2026-11-01）中当前
缺 `--json` 的只有结构性豁免 `ui`（阻塞式 uvicorn serve，无单发输出
面）。探针复核命令：

```
.venv/Scripts/python.exe -c "import sys; sys.path[:0]=['src','tests/unit']; \
  from test_w2_c_json_coverage import _missing_json; print(_missing_json())"
# 实测 2026-11-01: ['ui'] → WITHOUT_JSON=1
```

新叶漏带 `--json` 不会立刻被肉眼发现，但合流全量门必红——这正是
"定向绿、合流红"清单把它列为第一钉的原因（对照表见
docs/how-to/new-surface-checklist.md）。

## 与 Super-agent Channel 的对照（思想吸收声明）

> 来源：DeepSeek `deepseek-ai/dsh-superagent-prototype`
> （https://github.com/deepseek-ai/dsh-superagent-prototype ，MIT
> License，Copyright (c) 2026 DeepSeek Harness Team——许可经实读
> LICENSE 原文核实，见 runs/aurora_o/superagent_absorb/ABSORB.md §1.1）。
> 本节为**思想转述 + 术语对照**，零代码复制；对方 README 明示其
> published code 与论文有差，对照仅到其原型 docs 实读面。

对方 Channel 组件回答的问题与 rfauto 信道分域同构——哪些出口存在
（allowed）、往哪个信道发什么形态（send）、外部会话怎么接进来（link）。
思想层面的对照：

| Super-agent Channel 面向 | rfauto 对应 | 形态 |
|---|---|---|
| 出口可用面的声明与约束 | CLI 叶必带 `--json` + MCP 工具注册 + 信封构造器 | 门清单纪律（棘轮只收不放） |
| 面向人的消息形态 | rich 人读分支（红字/表格/建议提示/stderr 指针） | `_emit` human 分支 |
| 面向 agent 的消息形态 | JSON 信封（ok/error/skipped 三态） | `_emit` --json 分支 + 契约 |

其"注意力经济学"三条设计律（少概念、少设置、面板只显示需要人的
事——原型 docs/000-philosophy.md 实读转述）在 rfauto 的对应物：
基类+注册表模式（加组件不加重概念，硬规则 3）、信封三态
（三种形状覆盖全部返回，少概念）、verdict 门表如实 FAIL/PARTIAL/
UNKNOWN（门红才值得人看，同锚与判据制度 docs/explanation/
anchor-and-verdict.md）。

## 四域策略单源（aurora_p F3，2026-11-02）

前文讲的是 CLI 双信道；机器可辨的输出信道实际有**四条**：
`cli-human` / `cli-json` / `ui-sse` / `mcp`。四域各自的错误/成功输出
形态规则（exit 码、信封字段、SSE 事件名、无内部泄漏）已收成一张
**描述性单源表**：

- 表：`src/rfauto/service/channel_policy.py` 的 `DOMAIN_POLICIES`——
  逐域 `surface`（发射面锚）/`success_shape`/`error_shape`/
  `failure_invariants`（机器可查不变量）/`leak_bans`（泄漏禁令）/
  `notes` 六字段；`get_policy(domain)` 取表、`assert_surface_matches`
  自检（观察面 vs 表逐条比对，冲突抛 `PolicyMismatch`）。表是**现状
  的描述不是新行为**：零 rfauto import（分层合规+结构上不可能改变
  任何发射路径）、不被任何发射面引用、禁 `__all__`（public_api 金
  快照零扰动，event_bus 同款纪律）。
- 四条真实发射面：CLI 双域=`cli/domains/_core.py::_emit`/
  `_emit_usage_error` 双分支（上文"单源出口"节）；ui-sse=
  `ui/routes/event_bus.py::sse_frame`/`control_frame` 帧形态单源 +
  `ui/server.py::_param_error_handler`（400 信封）；mcp=`mcp_tools/`
  `@mcp.tool` 薄壳（失败=返回 ok=False 信封，全包零 raise——AST
  计 0）。
- 结构钉：`tests/unit/test_channel_policy.py`（21 用例）把表里每条
  `failure_invariants` 与发射面**当前源码结构/探针实测**逐条对上
  （AST 抓 exit 码与分支结构、真调 `sse_frame`/`control_frame` 探针、
  mcp 全包 raise 计数）；含 3 条变异探针（改假面字段→钉红）钉自检
  函数自身有效。表与现状冲突即红（诚实性：钉描述现状，行为变更须
  同笔改表）。
- Channel 对照的落位：allowed↔表 `surface` 锚（四域出口可用面）；
  send↔`success_shape`/`error_shape`（各域消息形态）；link↔CLI exit
  码约定（调用方分支语义）/SSE `id` 行 Last-Event-ID 续传锚/MCP
  stdio JSON-RPC 会话。
- 审计结论（2026-11-02）：四域主体一致，三处不一致**如实登记未现
  场改**——`_watch_poll` 超时红字行与 `_load_json_file`/`_kv_floats`
  参数错红字在 --json 下走 stdout（VI-5 W6-B 域内违反）、runs 桥
  error 帧裸 `{errors:[…]}` 非统一信封；MCP 零 raise 是约定非结构
  强制（无全局 handler）。清单与建议见
  `runs/aurora_p/f3/AUDIT.md` §2/§4（**证据区指针，非文档依赖**），
  处置由主代理裁量另派。
  **已清偿（aurora_p F3L1，2026-11-02）**：I-1/I-2/I-3 三处已修——
  JSON 信道失败路径全走信封（超时帧/usage 错 exit 2 信封/runs 桥
  error 帧信封），人读信道红字与 exit 码逐字节原样（修前/修后
  bytecmp 对照在 `runs/aurora_p/f3l1/`，钉
  `tests/unit/test_aurora_p_f3l1_channel_envelope.py`）；MCP 零
  raise 硬化仍为候选（§4，未动）。
- 本节引用符号均 grep/实测复核（#222 家法，复测时点 2026-11-02）。

## 给贡献者的推论

- 写新 CLI 叶：`--json` 旗标必带；输出一律经 `_emit`/`_emit_usage_error`
  单源出口；服务返回走 envelope 构造器，PR 里出现新的裸 `{"ok": ...}`
  字面即契约违约（修复类改动同样走构造器）；
- 写服务函数：失败信息是完整句子（含现场键值），不做错误码路由；
  hints 提示词措辞指回内核守卫原文，不发明新阈值；
- 写消费脚本：分支只看 `ok`，失败读 `errors` 列表逐条渲染；`--json`
  输出前的 stderr 内容（如日志）不参与解析；
- 看到 `--json` 棘轮红：说明有新叶漏旗标或有人动了豁免清单——方向
  是补旗标，不是扩大豁免（豁免须入 `W6B_EXEMPT` 并记因）。
