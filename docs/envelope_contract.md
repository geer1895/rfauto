# 服务层 JSON 信封契约（AU-2 统一批）

> 适用面：service 层全部 JSON 进出函数（规则 4）及其 CLI/MCP/UI 薄壳。
> 单源：`src/rfauto/service/envelope.py`（`ok_envelope` / `error_envelope` /
> `skipped_envelope` / `normalize_errors`）。契约自身版本：
> `ENVELOPE_SCHEMA_VERSION = "1.0"`。
> 测试门：`tests/unit/test_envelope_contract.py`。

## 1. 三态定义（status 口径）

| 态 | 形状 | 语义 |
| --- | --- | --- |
| ok | `{"ok": True, **payload}` | 调用成立且有结果。payload 键按域自定。 |
| error（failed） | `{"ok": False, "errors": [str, ...], **diag}` | 调用失败。`errors` **恒为 `list[str]`**（str 入参自动包单元素列表，None → 空列表，见 `normalize_errors`）。diag 常见键：`run_id`/`stage`/`warnings`。 |
| skipped | `{"ok": True, "skipped": True, "reason": str, **diag}` | 调用链成立但本项未产出结果。`reason` 必给且人/Agent 可读。**skipped≠failed**：失败要修，跳过是如实声明（前置不满足/能力不适用）。历史前置不满足语义的调用点（remote_ads_service）显式传 `ok=False` 保持原形状。 |

判读规则（消费者口径）：

1. 分支判据只看 `ok` 布尔；`skipped` 是 ok 信封上的附加标记，不参与成败判断。
2. 失败信息一律读 `errors` 列表并逐条渲染；**禁止单数 `error` / 裸 `reason` 作为新消费面的失败读取键**（历史形态见 §3）。
3. `errors` 元素是人/Agent 可读的完整句子（含现场键值），不做错误码路由。

## 2. schema_version 按域推广规则

- 范本：`service/pdn_service.py`（`PDN_SERVICE_SCHEMA_VERSION = "1.0"`，逐返回信封落键，`result.setdefault` 兜底透传壳）。
- 每个产出结构化产物的 service 域一个模块级常量 `<域>_SCHEMA_VERSION`，
  值=该域**当前事实版本**（首批推广统一 `"1.0"`——历史产物无键照读，
  键出现即视为该域结构受契约约束，后续破坏性形状变更必须升版本）。
- 消费面向后兼容：读侧 `d.get("schema_version")` 缺省按"旧档案"处理，
  **不得**因无键拒绝（旧 runs/ 归档永不全量重写）。
- 与 `recipe_version`（配方 schema）/ `schema_version`（插件参数 schema，
  #106）语义区分：域常量只描述**该 service 返回结构**，不进缓存键。

已推广域（本批）：

| 域 | 常量 | 位置 |
| --- | --- | --- |
| pdn | `PDN_SERVICE_SCHEMA_VERSION` | `service/pdn_service.py`（范本，既有） |
| diagnosis | `DIAGNOSIS_SCHEMA_VERSION` | `service/diagnosis_service.py` |
| anchors 报告 | `ANCHORS_REPORT_SCHEMA_VERSION` | `service/anchors_service.py` |
| league | `LEAGUE_SCHEMA_VERSION` | `service/league_service.py` |

## 3. 历史遗留形态（不改形清单，新代码禁新增）

零破坏铁律：以下形态的**既有**调用点本批不改（改形即破坏既有消费者），
消费方兼容读法=按序回退 `errors` → `error` → `reason`：

1. **单数 `error` 键**（约 30 处）：`mcp_server.py` 异常壳（MCP 线上契约，
   `test_mcp_server.py` 多处断言钉住）、`ui_service.sandbox_diff/promote`
   （镜像 RecipeSandbox 惯例）、`diagnosis_service`（`test_dp2_diagnosis.py`
   断言 `r["error"]`）、`anchors_service` 部分入口。
2. **裸 `reason` 代错误**（league_service `{"ok": False, "reason": ...}`）：
   league 域失败信封形状；本批只加 `schema_version` 戳不改键。
3. **结构化 gate 信封**（api.py `agent_propose` L1/L2）——已于 W3fix 批
   （2026-10-05）迁走：现为 `error_envelope(violations/issues, stage=...,
   gate=...)`（stage/gate 诊断键保留，errors 承载门内容摘要），本族就此
   退出遗留清单。
4. **节级 status 形态**（`active_chain_service` 的
   `{"status": "skipped", "reason": ...}`、`array_service` 的
   `{"skipped": True, "reason": ...}` 子结果）：非顶层信封（嵌入行/节），
   加 `ok` 键反而污染行结构。
5. `run_once_async`/`wait_job` 等把上游信封重拼的调用点（`{**last,
   "ok": True}`）：透传合并语义，保留。

> 现值冻结账（I-07，对齐 R5-05 建议）：单数 `error` 冻结 200、裸 ok 随批
> 收敛 565→563→552（2026-10-04 ge8e W2 后现值）、本节遗留族地板 522——
> 逐批数字与构成见 `tests/unit/test_envelope_contract.py`
> `_FROZEN_BARE_OK_RETURNS` 行内注释（AST 全量扫描口径）。

## 4. 本批已改走单源的面（抽查锚）

- `service/api.py`：全部 ok/error 族（validate_recipe/dry_run/run_once/
  agent_propose/agent_apply/analyze_surrogate/compare_runs/poll_job/
  replay_run/get_metrics/generate_report_for_run/run_link/recipe_migrate/
  repro_export/doctor/start_tune，含 W3fix 批迁走的 agent_propose L1/L2
  gate 信封）。例外：§3.1 遗留族与
  `append_audit_log` 审计记录（非信封）。
- `mcp_server.py`：`errors` 列表族 + 纯 ok 族（synthesize_mline/bpf、
  budget_analysis、correlate_measurement、diagnose、save_campaign_plan、
  export_report_pdf、cancel_job ok 态）。例外：§3.1 单数族。
- `service/ui_service.py`：全部 ok/error 族（read_run_events、recipe_view/
  save/create、tune_trials、calibration、sparams/smith/field/pareto/
  feasibility、datasets/anchors/uq 页）。例外：§3.1 两处 sandbox 壳。
- `service/remote_ads_service.py`：skipped 族五处
  （`skipped_envelope(..., ok=False)`，形状逐键不变）。

新代码规约：service 返回信封一律走 `envelope.py` 构造器；PR 里出现新的
裸 `{"ok": ...}` 字面量即契约违约（`test_envelope_contract.py` 对已改域
抽形状，见该文件 docstring 的抽查范围）。守卫正则已多行感知（ge5 审查
P2-1 修复：`return \{\s*"ok"` 跨行匹配）。**AST 级全量守卫（ge6 followUp
P2-1 残余清偿）**：`TestAstBareEnvelopeFaceGuards` 以 AST 扫全
`service/*.py` + `mcp_server.py` + `mcp_tools/**/*.py`——裸 ok 信封
（return 字面量 + 一跳变量中转 `r = {...}; return r`）存量冻结
（只禁增长不禁收敛，冻结值随迁移下调）+ 单数 error 遗留族增长即红；
正则守卫曾披露的两类残余盲区（变量中转形态、四面之外 service 文件）
就此闭合。

## 5. 数值清洗助手单源（附带收敛）

`_as_float` 容错族收敛到 `core/num_utils.coerce_float`（显式策略参数
`accept_str` / `accept_bool` / `finite_only`），三处历史实现改为薄包装、
逐位行为不变：`core/mesh_artifact`（str+bool 放行）、
`pipeline/log_distiller`（bool 排除）、`service/league_service`
（仅原生数值，不查有限性）。
