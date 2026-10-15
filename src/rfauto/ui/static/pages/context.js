/* rfauto 工作台共享状态单源（aurora_d UI-R2 自 pages.js 拆出）：
   T=工具集（app.js initPages 注入，Object.assign 就地装配——对象同一性
   即拆分前语义）；S=跨页共享状态（currentRunId/chatLog/各页记忆字段）；
   _activeView=当前激活页（showPage 单源写、轮询/SSE 可见性守卫读）——
   模块私有 let 经访问器跨模块读写。 */

export const T = {}; // 工具集（initPages 注入）
export const S = { currentRunId: null, chatLog: [] };
/* 当前激活页（showPage 单源写入）——轮询回调"当前页守卫"的依据。 */
let _activeView = "dashboard";

/* _activeView 跨模块访问器（拆分接缝）：写=router.showPage 单源；读=轮询
   守卫/SSE 恢复守卫/tools 深链守卫。可变原语留在唯一状态模块，跨模块经
   访问器读写（ESM import 绑定只读，写面收敛）。 */
export function setActiveView(v) {
  _activeView = v; // aurora36 W2-B：页面可见语义单源（轮询当前页守卫消费）
}
export function getActiveView() {
  return _activeView;
}
