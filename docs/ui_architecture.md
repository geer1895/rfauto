# UI 架构指南：工作台壳的扩展者入口

> 本文是**开发者扩展 UI 的入口文档**：前端 ESM 依赖结构、状态管理、
> 页面生命周期、i18n 体系与契约门的完整地图。全部数字为 2026-10-19
> 工作树静态实测（import 提取/逐键 grep/门脚本实跑），非沿用历史审计；
> 文中不复制端点清单与键清单——清单会烂，指针不会。
> 分工：系统级"为什么"（双 HTTP 面/事件总线）见
> [分层架构「UI 架构」节](explanation/layered-architecture.md)；
> 视觉设计系统见 docs/ui_development_guide.md；
> 动手清单见 [how-to/new-surface-checklist.md](how-to/new-surface-checklist.md)、
> [how-to/i18n-keys.md](how-to/i18n-keys.md)、
> [how-to/ui-performance-and-contract-gate.md](how-to/ui-performance-and-contract-gate.md)。

## 0. 一条红线先说：零构建

`src/rfauto/ui/static/` 是**原生 ESM 零构建**前端：`index.html`（891 行
单壳）+ 41 个 JS 模块（10,278 行，vendor/ 除外）——原生
`<script type="module">` 相对路径 import，浏览器直跑，无打包器、无
node_modules、无 TS。**改任何前端代码都不需要构建步骤**，刷新即生效；
反过来，禁止引入任何需要编译的形态（JSX/TS/打包器）——这是结构性
红线，不是偏好。数据解释逻辑（YAML/CSV 解析、数值派生）全在 service
层，前端只渲染。

## 1. 依赖六层（实测：41 模块 · 177 条静态边）

`import ... from "./..."` 静态边实测 179 条（from-引用去重口径，W9-S3
复核同值；动态 `import()` 另计），入度排序（前八）：

| 模块 | 入度 | 角色 |
|---|---|---|
| pages/dom.js | 30 | esc/escAttr/fmtNum/errorText/renderMarkdown/help 单源 |
| pages/context.js | 30 | T 工具集 + S 状态 + _activeView 访问器 |
| pages/api.js | 25 | apiFetch/viewSignal/composeSignals 请求管道 |
| pages/kit.js | 19 | 通用 UI 件 14 件（kitTable/kitBadge/kitEmptyState/kitErrorPanel…） |
| pages/i18n.js | 16 | 双语词表 + t() |
| theme.js | 14 | 主题单源（THEME_KEY/applyThemeDom 双写单源） |
| pages/router.js | 13 | VIEWS 注册表 + showPage + 两级 hash 路由 |
| pages/charts.js | 7 | echarts 生命周期/主题重放/导出桥 |

分层自底向上，**底座五件零本地依赖**（node 裸 import 可测，是行为钉
的根基）：

```
L0 底座（零依赖）: pages/api.js · pages/i18n.js · theme.js · pages/sortable.js · pages/context.js
L1 DOM 基础:       pages/dom.js（唯一消费 i18n 的底层件）
L2 组件层:         pages/kit.js · plotcard.js · chart_export.js · pages/filebrowser.js
L3 路由:           pages/router.js
L4 视图层:         23 个 pages/view_*.js
L5 门面/外壳:      pages.js（薄入口+全量 re-export）→ app.js · palette.js
```

- `pages.js` 是门面：组装 VIEWS/PAGE_CTX 注册表、initPages 装配、
  既有公开导出面 54 名全量 re-export——app.js/palette.js 只 import
  门面，不直接 import 视图。
- plotcard/chart_export 不经门面，被 app.js 直接消费（图表域旁路）；
  palette.js 经门面拿全量导出并直连 api/i18n/dom。
- 新增底层能力时先问分层：请求/词表/主题/状态四类进 L0，DOM 工具进
  L1，可复用 UI 件进 L2——视图层禁止反向被底座 import。

## 2. 唯一的环：router ↔ view_tools ↔ kit（靠纪律不靠结构）

全图唯一环簇（DFS 实测 5 条记录同簇）：

```
pages/router.js → pages/view_tools.js → pages/kit.js → pages/router.js
```

现状安全：两侧只在**函数体内**消费对方绑定、零顶层执行（ESM 延迟
绑定语义下求值序无恙）。脆弱面：环内任一模块将来加顶层执行（模块级
常量调用对方导出）即 boot 期 TDZ/undefined 崩。**纪律：改这三个文件
时禁止新增模块级执行语句**；结构性断环是已登记余项，动手前先读
router.js 头注的环成因说明。

## 3. 页面与路由：26 页 · 23 懒加载 · 两级 hash

- VIEWS 注册表 26 页（index.html 侧栏 26 个 data-v 与之逐键对齐——
  有注册序钉）。首屏静态装配只有两件：view_tools（router opener 的
  静态依赖）+ view_dashboard（落地页）；其余 24 页经 `_lazyView`
  动态 `import()` 按需拉取（guide 亦懒加载，W9-S3 复核 26−2=24），
  模块缓存命中后零开销，加载失败收敛为
  单页错误面板+toast（不留整站白屏）。
- **一文件多页**：view_data.js 服务 datasets/anchors/uq 三页、
  view_fieldviz.js 服务 farfield/field 两页——懒加载粒度=文件，
  首访任一页拉全文件。新建页面若与既有域同源，先考虑并文件还是
  独立文件的代价。
- 路由两级：`#/page` 裸页 + `#/page/<arg>` 参数页；解析单源
  `parseRoute`（纯函数，node 行为钉）。参数分发走 `_ROUTE_OPENERS`
  注册表（现 7 页：detail/tools/campaign/sparams/calibration/
  loopboard/reports）——新增参数化页面=实现带参 opener+登记一行。
- 深链待选纪律：`_pendingLinkOpener` 工厂（campaign/sparams/
  calibration/loopboard/reports 五对 open/consume）——open 记待选 id
  拉页、页面渲染清单后 consume（读取即清零，不残留跨页污染）。
- hash 回写一律 `_syncRouteHash`（replaceState：不产历史条目、不触
  hashchange，避免与分发互激）。

## 4. 状态管理：S 已收敛单键 + 键契约表

**S = `{ currentRunId }`——全站唯一跨页共享键**（context.js 头注即
键契约表：属主 router、写面唯一、生命周期会话级）。历史上曾 19 键
堆在全局对象上，已按审计收编：16 个单模块私有键降级为各视图模块级
`let`（`_chatLog`/`_dashData`/`_spOverlay`…逐键属主见 context.js
契约表）。规则：

- **新增共享键先过契约表**：在 context.js 登记属主/写面/生命周期
  三行，写面收敛到唯一模块；只有"真跨页"才允许进 S。
- 模块私有状态用模块级 `let`，命名 `_` 前缀——不进全局命名空间，
  互踩面为零。
- `_activeView`（当前激活页）不走 S：模块私有 let + `setActiveView/
  getActiveView` 访问器（写=router.showPage 单源；读=轮询/SSE 可见性
  守卫）——可变原语留在唯一状态模块，跨模块经访问器读写。
- **localStorage 持久层 6 键**（全部 try/catch 守卫、无敏感数据）：
  rfauto-theme / rfauto-locale / rfauto-chat / rfauto-chat-geo /
  rfauto-widgets / rfauto-widget-span。新增持久键在此登记同笔。
- 事件面**无总线**（前端侧）：数据刷新三通道各司其职——SSE
  （pages/sse.js，EventSource+退避+隐藏收束）覆盖 tune/campaign/
  detail；轮询（pages/polling.js，当前页双守卫+隐藏暂停）覆盖
  loopboard/tune 兜底；`PAGE_CTX.refresh`（palette 刷新当前页）覆盖
  24 页。唯一 window 级 CustomEvent 桥=`rfauto:export-chart`
  （palette→charts，固定契约零 payload）。进程内侧的统一事件流
  （event_bus→SSE）见分层架构文档，前端 sse.js 消费同一信封。

## 5. PAGE_CTX 生命周期：24 页登记 + 2 页有理由豁免

`router.js PAGE_CTX` 是页面生命周期钩子注册表（增量式：渲染函数=
enter 面不动，只登记钩子）：

- **refresh()**：palette「刷新当前页」的局部刷新入口（数据拉取与壳
  渲染分离；未登记页回退 showPage 整页重进）。
- **leave()**：离页收束（loopboard/tune 的停表语义在此）。

实测登记态：24/26——dashboard 静态直登记 + 23 懒加载页经 `_lazyCtx`
包装（动态 import 恒缓存命中零开销）。豁免双页各有成文理由
（pages.js 自注）：**guide**=纯静态说明书壳零数据面；**import**=纯
表单页，refresh 重进反而丢编辑态。新建页面默认登记 refresh；有轮询
面/交互态才加 leave。切换时序：`showPage` 先调前页 `leave()`（异常
不阻切页，#105 best-effort）再激活新页——离页收束先于进入。

## 6. 渲染与转义纪律（全站实测：innerHTML 271 · textContent 134 · esc() 278；grep 原始出现次数含头注注释提及，代码语句口径略低——数字看趋势，注册序/契约以门为准）

- 全量重建模型：每页 refresh/筛选为 innerHTML 整壳/表体重建——在
  数据视口规模（≤500 行/≤2000 点降采样）+ content-visibility/防抖/
  虚拟列表缓解下实测无感；**不引 diffing/虚拟 DOM**（违反零构建红线
  且无收益场景）。
- 转义三层纵深：① `esc()` 五字符集单源（dom.js），模板串插值一律
  过 esc 或 t()；② markdown 经 DOMPurify 硬错化（缺库即拒绝
  innerHTML 降级 textContent）；③ CSP script-src 哈希钉+零内联。
  实测裸插值仅个位数且逐行核为数值/预转义来源——**新增 innerHTML
  行有扫描钉，别手滑**。
- **数据 vs 文本分层**：t() 产出=开发侧可信文本（词表值永不含
  HTML）；API 动态数据一律 esc/escAttr——禁止 t() 包数据、禁止把
  数据拼进词表值（i18n.js 头注纪律，违者返工）。
- 事件接线双惯语（有判据）：`onclick=` 赋值（73 处）=重渲染幂等
  语义（整壳重建后重绑零残留）；`addEventListener`（37 处）留给
  window/键盘/matchMedia 等常驻监听——同一文件别混用两种语义。

### 6.1 错误/空态呈现判据（单源收编，W14-S2 成文）

同类失败一种长相——四条判据按语义分派，**禁止内联 `✗ span` 自绘**：

| 语义 | 单源件 | 说明 |
|---|---|---|
| 页面数据面失败（进页拉取/局部重拉失败，错误占据内容区） | `kitErrorPanel(msg, retryId?)` | badge+esc 错误串+可选重试钮；文案走 `errorText()` 信封回退链（errors→error→reason，裸读 `d.error` 在 errors 信封下渲染 "undefined"）；可重入拉取才带 retryId，一次性动作失败不带（gallery 闭式失败点先例） |
| 一次性动作反馈（提交/保存/启停成功失败、瞬时告知） | `T.msg`（app.js `msg()`，#msg toast） | 4s（ok）/8s（err）自动消退；**保留给动作反馈语义**，不做页面数据面错误载体 |
| 破坏性动作确认（清空对话/接管等单击即毁操作） | `kitConfirm`（kit.js） | 模态+焦点三件套，初始焦点落取消钮 |
| 请求成功但数据为空 | `kitEmptyState`（+`bindEmptyStates`） | 空态三件式，跳转钮 data-empty-view 自动接线 |

历史四态并存（kitErrorPanel/内联 ✗ span/T.msg 直呼/页内自定义分支）已
按此判据收编：playground×2/profile/tools 内联 ✗ 点迁 kitErrorPanel
（W14-S2，`color:var(--err)'>✗` 计数钉 5→1 同笔）；queue 决策表 ✗ 点
按跨席注释豁免（表格行内语境，非页面级错误）。

### 6.2 kit.js 组件总账（16 导出，W14-S2 记账；合同全文在各件块注释）

组件合同写在 kit.js 文件头注/块注释（本项目纪律：文档只给地图，清单
以代码为准）。消费文件数=2026-10-19 W14-S2 工作树 grep 实测（kit.js
自身与测试引用不计）：

| 组件 | 签名（参数 → 返回） | 用途 | 消费文件 | 行为钉 |
|---|---|---|---|---|
| kitTable | `({columns, rows, rowHtml, rowsHtml, empty, sortable, caption})` → `<table>` 串 | 数据表同构壳；columns=null 为键值表形态；rows+rowHtml 与 rowsHtml 二选一；caption=sr-only 读屏命名（kit 内 esc）；单元格转义责任在调用方 | 10 | test_ui_kit + test_w5s23（caption/恶意串） |
| kitPanelHead | `(title, actions?, attrs?)` → panel 壳串 | `<div class='panel'><b class='title'>` 头壳单源；title=调用方先 esc 的预构建 HTML | 8 | test_ui_kit |
| kitBadgeCls | `(status)` → 类名串 | 状态→badge 类映射单源（未列状态一律 muted） | 3 | test_ui_kit |
| kitBadge | `(text, status)` → badge 串 | 按状态查类渲染（T.badge 单点 esc，缺席回退同串实现） | 4 | test_ui_kit |
| kitVerdictBadge | `(verdict, label?)` → badge 串 | 二元判定：PASS→ok，其余一律 FAIL/err；label 覆盖缺省字面 | 3 | test_ui_kit |
| kitBoolBadge | `(ok, yes, no)` → badge 串 | 布尔可用性：true→ok / false→err | 3 | test_ui_kit |
| kitSkeleton | `(n)` → 骨架条串 | 首拉占位条（shimmer 纯 CSS，reduced-motion 降级） | 3 | test_ui_kit + test_ui_polish |
| kitSkeletonRows | `(rows, cols)` → `<tr>` 骨架行串 | 表体骨架（**只能进 tbody**） | 2 | test_ui_kit |
| kitEmptyState | `(text, cta?)` → 空态三件式串 | 图标+一句话+动作钮；cta={label,view} 走 data-empty-view 自动接线 / {label,id} 调用方自接（双协议在档）；text=trusted 开发侧文案 | 11 | test_ui_kit + test_ui_polish |
| bindEmptyStates | `(root)` → void | `[data-empty-view]` 钮 → showPage(view)；innerHTML 赋值后调用，幂等；node 语境 document 守卫直返 | 3 | test_ui_kit + test_ui_polish |
| kitErrorPanel | `(msg, retryId?)` → 错误面板串 | badge+esc(msg)+可选重试钮（id 调用方接线）；错误呈现单源见 §6.1 | 11 | test_ui_kit + test_ui_polish（retry 接线） |
| kitClickRowAttrs | `({role?, label?})` → 行属性串 | 可点行 innerHTML 形态：role 缺省 button，tr 行传 role:null 保表语义 | 8 | test_ui_kit + test_ui_a11y_rows（12 站点台账） |
| kitApplyClickRowAttrs | `(el, opts)` → el | 同上 DOM 侧（setAttribute 逐键同口径） | 3 | test_ui_a11y_rows |
| bindClickRows | `(root, onActivate, selector?)` → void | click+Enter/Space 同一 onActivate（preventDefault 防滚屏/页顶跳动） | 11 | test_ui_a11y_rows |
| kitConfirmHtml | `({title, body, danger, okLabel?, cancelLabel?})` → 确认面板串 | 纯串构建（data-act 接线锚）；danger=true 确认钮红档；缺省钮面 common.confirm/cancel | —（kit 内部+钉） | test_ui_kit |
| kitConfirm | `(opts{onOk,…})` → backdrop 元素（node 返回 null） | 破坏性动作确认模态：遮罩+焦点三件套+Esc/遮罩关+初始焦点落取消钮；onOk 异常吞掉不阻关闭 | 2（agent/loopboard） | test_ui_kit |

sortable 两件（makeSortable/mountSortableTables）独立于 kit
（历史拆分产物，功能与 kitTable `sortable` prop 打通）——判定维持，
在此一并记账。

## 7. i18n 体系：505 键 · 18 域 · zh/en 双档

- 单源词表 `pages/i18n.js`（键=`<域>.<语义>`，值 `{zh, en}` 双档；
  实测 505 键/18 域——tools 140/dashboard 67/uq 47/guide 41/datasets
  34/nav 29/agent 27/anchors 24/…）。t(key, params) 支持 `{name}`
  占位符；locale 持久化 rfauto-locale（LOCALE_MODES=["zh","en"]，
  zh 缺省）。
- **三个注入口**：textContent / placeholder / aria-label——零
  innerHTML（词表值不含 HTML；`&lt;` 等字符实体例外，见头注）。
- 接线面半程是**已登记现状**：16/41 文件 import i18n（门面 pages.js
  +palette+dom/kit 底层件+12 视图：tools/gallery/queue/dashboard/
  runs/detail/sparams/agent/timeline/data/guide/loopboard）；
  其余视图仍中文字面。防恶化机制已
  常驻：`scripts/check_ui_i18n_coverage.py` 字符级状态机扫字面量
  hardcode + `scripts/ui_i18n_baseline.json` **只减不增棘轮**（实测
  在账 33 文件/总 Han 5417 字符）+ test_ui_i18n 六层钉。新代码一律
  t()；摸到旧视图顺手迁键（how-to/i18n-keys.md 有全流程）。

## 8. 契约门与测试面（改 UI 必跑的门）

| 门 | 脚本/测试 | 实测口径（2026-10-19） |
|---|---|---|
| 前后端契约棘轮 | `python scripts/check_ui_contracts.py` | 前端 /api/ 字面调用 61 形态 ⊆ 服务端路由 65；悬空调用豁免表**基线必须为空**；无消费端点豁免 4 条只可删不可加 |
| i18n 硬编码棘轮 | `python scripts/check_ui_i18n_coverage.py` | 40 文件对账零回潮；基线只减不增 |
| 行为钉 | tests/unit/test_ui*.py 族（59 个文件） | 底座五件 node 裸 import 行为钉 + jsdom 零依赖；注册序/导航/路由/SSE/主题/i18n/xss 各有专钉 |
| 安全面 | test_w1e_ui_csp + test_ui_auth + test_ui_xss_escape | CSP 头值单源比对；写端点 Bearer（env `RFAUTO_UI_TOKEN`）401/放行/读豁免；转义逃逸 |

新增前端调用或服务端端点时：先在 server.py Route 表登记（或前端
调用），门红即对账——**悬空调用/死路由在静态门暴露，不等真机点击**。
性能面（壳首载/vrows/降采样）的门口径见
how-to/ui-performance-and-contract-gate.md。

## 9. 服务端壳（简节——详见分层架构文档）

`ui/server.py`（418 行）只做装配：Route 表（67 条，含 `/`、`/static`
与可选 `/runs` Mount）+ 中间件链（GZip → CSP+安全头批（csp.py 80 行
单源）→ CacheControl 分域）+ serve 启动（**loopback 127.0.0.1:8642
缺省**，非回环显式闸）。全部 API handler 按域机械拆在 `ui/routes/`
12 个模块（runs/recipes/tune/agent/importer/measurement/insight/
fieldviz/data/tools/events + event_bus 统一事件流）；参数守卫单源
`ui/params.py`；run_id 路径守卫单源 `service/_helpers.py safe_run_id`
（全部 `RUNS_DIR / run_id` 拼接点先经守卫）。写端点鉴权：env
`RFAUTO_UI_TOKEN` 设定时 POST/PUT/DELETE/PATCH 要求 Bearer（服务端
meta 标签同源中继→api.js 装配期自动接线；未设=零行为变化）。程序化
REST 面在 `service/rest_api.py`（/api/v1，8644）——两个 HTTP 面共
用同一 service 层，互不转发。

## 10. 扩展一个页面的最小路径

1. **定域**：数据/判读/平台哪类？复用 view_data（数据三页同壳）还是
   新文件？
2. **实现** `pages/view_<x>.js`：`export function page<X>(currentRunId)`
   + 可选 `export const <x>Ctx = { refresh, leave }`；壳渲染幂等
   （innerHTML 重建语义），数据面走 `apiFetch`，文本走 `t()`，动态
   数据一律 esc。
3. **注册三行**：pages.js 加 `_lazyView` 别名 + `Object.assign(VIEWS,
   {...})` 一键 + `Object.assign(PAGE_CTX, {...})` 一键（有数据面就
   登记 refresh）；index.html 侧栏加 nav 项（data-v 与键同名）+
   i18n 词表补 `nav.<x>`。
4. **过门**：`check_ui_contracts.py` + `check_ui_i18n_coverage.py` +
   test_ui 注册序/导航相关钉；有新 /api/ 端点则服务端 Route 表同笔。
5. **对照清单**：how-to/new-surface-checklist.md（完整版含可访问性
   与性能钉）。

## 11. 已知结构性余项（诚实面，动手前先读）

- 环（§2）：router↔view_tools↔kit 靠"函数体内消费"纪律保命，断环
  已登记未动手。
- 视图层唯一横向边：`view_sparams.js → import { drawSmith } from
  "./view_fieldviz.js"`——sparams 懒加载连带 fieldviz 全文件；
  drawSmith 归属应在 charts 绘图域（迁移是登记项，勿在无关批次
  顺手改——绘图输出有 golden 快照钉）。
- i18n 半程（§7）：接线 14/41 是现状非目标态；棘轮只防恶化。
- 结构性余项的完整清单与依赖序见 内部证据目录
  （战役审计报告，历史文档——动手前以当时代码复核）。

---
*数字快照：2026-10-19 工作树静态实测（41 模块/10,278 行/179 边/
26 页/24 ctx/505 键/61 调用形态/65 路由/59 个 UI 测试文件；两门
实跑 PASS；W9-S3 复核批——179 边/kit 19/懒加载 24 页/i18n 接线
16 文件四处按当树复测回改；W14-S2 增量——§6.1 错误呈现判据成文/
§6.2 kit 16 件总账/505 键（common.offline·online）/趋势计数四处按当树复测）。文档只给结构，清单以代码为准——
本文与代码冲突时，以代码和门为准并回改本文。*
