# 解释：信封契约与 API 演进

> 这是一篇 explanation（解释文）：回答"为什么 service 层的 JSON 返回
> 要走统一信封、契约怎么在不破坏旧消费者的前提下演进"。规范面
> （条款原文）：docs/envelope_contract.md；守卫实现：
> `tests/unit/test_envelope_contract.py`。架构背景：
> docs/explanation/layered-architecture.md。

## 问题：一个业务面、四种消费方、无数种失败写法

rfauto 的业务只有一份（service 层函数），但消费方有四类：CLI（人+
脚本）、MCP server（LLM agent）、UI 工作台（浏览器）、程序化 REST
（第三方脚本）。如果没有统一返回形状，每个 service 函数都会发明自己
的错误表达——事实上历史上就是这么长出来的：单数 `error` 键、裸
`reason` 代错误、节级 `status` 形态、异构 diag 键……每一种在当时都
"手感顺手"，累积起来就是消费方必须逐函数特判的碎片化接口。

信封契约（AU-2 批定型）回答这个问题的方式，是把**成功与失败的形状
本身**变成契约：

| 态 | 形状 | 语义 |
|---|---|---|
| ok | `{"ok": true, **payload}` | 调用成立且有结果 |
| error | `{"ok": false, "errors": [str, ...], **diag}` | 调用失败；errors 恒为字符串列表 |
| skipped | `{"ok": true, "skipped": true, "reason": str, **diag}` | 链路成立但本项未产出结果 |

三条消费规则随之固定：分支只看 `ok` 布尔；失败信息读 `errors` 列表
逐条渲染；错误消息是人/agent 可读的完整句子（含现场键值），不做
错误码路由——错误码路由要求消费者先学会码表，而完整句子对四类
消费方都天然可读。

## 为什么 skipped≠failed 是结构性的

失败要修，跳过是如实声明（前置不满足/能力不适用）。混用这两种语义
的代价是具体的：如果"license 预检不过"返回 failed，监控会把它当
故障告警；如果"文件损坏"返回 skipped，坏数据会静默绕过门。三态里
skipped 挂在 `ok=true` 信封上、不参与成败判断，正是为了让"链路健康
但无产出"与"链路断了"在消费端**结构性可区分**。远程战役路由
（`--remote`）大量依赖这个语义：无座位载荷的 remote 声明如实 SKIP，
不假绿也不假红。

## 单源构造器：怎么防止契约退化

约定靠自觉维持必然退化，所以契约配了三层机械防线：

1. **构造器单源**。`service/envelope.py` 提供 `ok_envelope`/
   `error_envelope`/`skipped_envelope`/`normalize_errors`，新代码的
   service 返回一律走构造器；
2. **AST 全量守卫**。`TestAstBareEnvelopeFaceGuards` 用 AST 扫全部
   `service/*.py` + `mcp_server.py` + `mcp_tools/`——裸
   `return {"ok": ...}` 字面量与"一跳变量中转"形态都在扫描范围内
   （正则守卫曾经的盲区，后来闭合）。存量的处理方式是**冻结棘轮**：
   只禁增长不禁收敛——`_FROZEN_BARE_OK_RETURNS`（2026-10-18 树面
   510）与 `_FROZEN_SINGULAR_ERROR`（同日 159）只能下调不能上调，
   迁移一批就把冻结值跟着下调一批（数值沿革全史留在
   `test_envelope_contract.py` 行内注释，AST 扫描口径）；
3. **抽查锚**。契约测试对已迁移域抽形状——构造器产出的信封缺
   `schema_version` 戳或形状漂移即红。

第三道防线引出本文的第二个主题：版本。

## schema_version：三个同名不同义的域

rfauto 里有三个都叫 "schema_version"（或很像）的东西，混淆会导致
缓存失效策略错误（#106 教训），必须分清：

| 名字 | 描述对象 | 版本失效策略 |
|---|---|---|
| `recipe_version` | 配方文件本身的 schema | 配方缓存按它判定重算 |
| `schema_version`（插件参数） | EMSolver 插件参数 schema | 插件参数校验面 |
| `<域>_SCHEMA_VERSION`（如 `PDN_SERVICE_SCHEMA_VERSION`、`ANCHORS_REPORT_SCHEMA_VERSION`） | **该 service 域返回结构** | 只描述返回结构，**不进缓存键** |

域常量的推广规则（范本 `service/pdn_service.py`）：每个产出结构化
产物的域一个模块级常量，首批统一 `"1.0"`——历史产物无键照读（读侧
`d.get("schema_version")` 缺省按旧档案处理，**不得**因无键拒绝），
键出现即视为该域结构受契约约束，**后续破坏性形状变更必须升版本**。

## 演进纪律：改形即升版、旧档案永不改写

信封契约最容易被低估的部分是它的历史兼容条款。rfauto 的 runs/ 归档
是**只增不改**的证据面——几个月前的 run 目录里躺着旧形状的 JSON，
任何"顺手把旧格式也统一了"的改动都是对档案的伪造。所以：

- **改形清单冻结**：历史遗留形态（单数 `error`（存量冻结账见
  `test_envelope_contract.py` 的 `_FROZEN_SINGULAR_ERROR` 行内沿革）、
  裸 `reason`、节级 status、透传合并……）逐条列进契约 §3，**既有调用点
  不改形**（改形即破坏既有消费者），新代码禁新增；
- **消费侧回退链**：兼容读法按序 `errors` → `error` → `reason`，
  让一个消费者读遍新旧两代档案；
- **收敛靠升版不靠改形**：遗留族的最终统一路径是按域升版（AU-2
  口径）——域升到 schema 1.1 时该域的新形状与新消费约定一起换挡，
  旧档案靠回退链照读。anchors/luneburg_lens/topology/terminology/
  parasitic/firmware/stats/bands/circulator/fet_noise 等域已按此路径
  迁移（2026-10-06 至 10-18 沿革见棘轮行内注释）。

这套纪律让 API 演进从"每次都赌博"变成"每次都记账"：破坏性变更必须
留下版本号与回退链，而不是依赖所有消费者同步升级——分布式世界里
消费者永远不会同步升级。

## 给消费者与贡献者的推论

- 写新 service 函数：返回只走 envelope.py 构造器；PR 里出现新的裸
  `{"ok": ...}` 字面量即契约违约（合流清单③——"修复类改动"同样
  走构造器，裸 `{"ok": false, "error": ...}` 手感顺手必触契约门）；
- 写消费方：分支看 `ok`，失败读 `errors` 列表；读历史档案走回退链；
  不要因为信封缺 `schema_version` 就拒绝数据——那是旧档案的合法
  形态；
- 改某域返回形状：先升该域 `<域>_SCHEMA_VERSION`，再动形状，同笔
  commit 带契约测试更新；
- 看到冻结棘轮红了：说明有人在守卫面之外新增了裸信封——方向是
  修代码，不是调大冻结值（棘轮只收不放）。
