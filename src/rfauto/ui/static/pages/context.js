/* rfauto 工作台共享状态单源（架构批 UI-R2 自 pages.js 拆出）：
   T=工具集（app.js initPages 注入，Object.assign 就地装配——对象同一性
   即拆分前语义）；S=跨页共享状态；_activeView=当前激活页（showPage 单源
   写、轮询/SSE 可见性守卫读）——模块私有 let 经访问器跨模块读写。

   ═══ 键契约表（架构批 W6-S2，R2 审计 §面2 / Top10 #1——v8 P8-8 欠账
   补账；S 收敛为 {currentRunId} 单键，16 个单模块私有键降级为各视图模块级
   let，行为逐位等价搬家。新增共享键须先在此登记属主/写面/生命周期）═══

   S（真跨页共享，唯一键）：
   ┌──────────────┬────────┬────────────────────────────┬──────────────┐
   │ 键           │ 属主   │ 写面（唯一=router.js）      │ 生命周期     │
   ├──────────────┼────────┼────────────────────────────┼──────────────┤
   │ currentRunId │ router │ openRun（主入口）+          │ 会话级，切页 │
   │              │        │ noteCurrentRunId（detail 页 │ 不清理       │
   │              │        │ 显式 id 重渲的旁路同步面）  │              │
   └──────────────┴────────┴────────────────────────────┴──────────────┘
   读者：router.showPage 分发 / view_detail（默认 id 与刷新）/ view_sparams
   （深链优先级链）/ view_reports（对比默认 A 路）。

   模块级降级键（属主=消费模块，模块私有 let，外部不可见——互踩面收编）：
   ┌─────────────┬───────────────────┬─────────────────────────────┐
   │ 键          │ 属主模块           │ 生命周期                     │
   ├─────────────┼───────────────────┼─────────────────────────────┤
   │ _chatLog    │ view_agent.js      │ 会话级（localStorage         │
   │             │                   │ rfauto-chat slice(-100) 持久）│
   │ _dashData / │ view_dashboard.js  │ 进页重拉；_widgetSet/_widget-│
   │ _widgetSet/ │                   │ Span 经 localStorage 持久    │
   │ _widgetSpan/│                   │ （rfauto-widgets /           │
   │ _kpiPrev    │                   │ rfauto-widget-span）；       │
   │             │                   │ _kpiPrev 会话级 count-up 记忆│
   │ _spOverlay/ │ view_sparams.js    │ 会话级（叠加清单/模式/选中） │
   │ _spRunId/   │                   │                              │
   │ _spMode     │                   │                              │
   │ _osRunId    │ view_optstack.js   │ 会话级（run 选中记忆）       │
   │ _ffRunId/   │ view_fieldviz.js   │ 会话级（farfield/field 两页  │
   │ _fvRunId/   │                   │ 选中记忆；_fv-polar 跨页带值）│
   │ _fvDump     │                   │                              │
   │ _dsAll      │ view_data.js       │ 进页重拉（三页共壳）         │
   │ _allRuns    │ view_runs.js       │ 进页重拉（上限 500）         │
   │ _galCards   │ view_gallery.js    │ 进页重拉                     │
   │ _cpRunId    │ view_campaign.js   │ 会话级（当前战役 run 记录）  │
   └─────────────┴───────────────────┴─────────────────────────────┘

   localStorage 持久键登记（6 键，实测 grep 计数；全部 try/catch 守卫、
   无敏感数据）：rfauto-theme（theme.js/pages.js）、rfauto-locale
   （pages/i18n.js）、rfauto-chat+rfauto-chat-geo（view_agent 对话历史与
   浮窗几何）、rfauto-widgets+rfauto-widget-span（view_dashboard 组件集与
   宽度记忆）。
   （跨页事件桥 window CustomEvent "rfauto:export-chart"：palette→charts，
   固定契约零 payload，登记在两模块头注。） */

export const T = {}; // 工具集（initPages 注入）
export const S = { currentRunId: null };
/* 当前激活页（showPage 单源写入）——轮询回调"当前页守卫"的依据。 */
let _activeView = "dashboard";

/* _activeView 跨模块访问器（拆分接缝）：写=router.showPage 单源；读=轮询
   守卫/SSE 恢复守卫/tools 深链守卫。可变原语留在唯一状态模块，跨模块经
   访问器读写（ESM import 绑定只读，写面收敛）。 */
export function setActiveView(v) {
  _activeView = v; // 架构批 W2-B：页面可见语义单源（轮询当前页守卫消费）
}
export function getActiveView() {
  return _activeView;
}
