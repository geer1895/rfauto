/* rfauto 工作台路由状态单源（aurora_d UI-R2 自 pages.js 拆出，
   aurora72 A4-C 块逐字节搬移）：两级 hash 解析 parseRoute（纯函数，
   node 行为钉）+ 参数页 opener 注册表 + showPage/openRun/openCampaign
   分发入口。视图注册表 VIEWS 由 pages.js 入口组装注入（本模块不
   import 各视图——避免路由→视图→路由整环）；tools opener 的
   toolsSelectKey 经 本模块→view_tools→本模块 的 ESM 环复用（两侧都
   只在函数体内消费对方绑定、零顶层执行——与拆分前 pages.js↔plotcard.js
   环同款安全性）。 */

import { S, T, getActiveView, setActiveView } from "./context.js";
import { _sseLeavePage } from "./sse.js";
import { toolsSelectKey } from "./view_tools.js";

/* 视图注册表（pages.js 入口按域组装注入——本模块不 import 各视图，避免
   路由→视图→路由整环）；键集与拆分前 showPage 内联 views 表逐键一致。 */
export const VIEWS = {};

/* ═══ R-1 页面生命周期协议（aurora72 W1-S3，R6 审计 R-1）══════════════
   PageContext 增量钩子注册表：VIEWS 键→渲染函数（=enter 面，既有
   `(S.currentRunId)` 签名兼容零变化）不动；本表只登记生命周期钩子增量——
   - refresh()：palette「刷新当前页数据」的局部刷新入口（数据拉取与壳渲染
     分离——dashboard 重铺组件面不重拉 /api/runs?limit=200、loopboard 立即
     拉一次看板）；未登记页回退 showPage 整页重进=旧行为。
   - leave()：离页收束（现 _pollStop 并入——loopboard 离页停表；未登记页
     零动作，_pollVisible 双守卫语义保留）。
   渐进迁移：页面实现钩子后在 PAGE_CTX 登记一行（懒加载页经 pages.js
   _lazyCtx 包装），其余页保持现状签名零迁移（全量迁移=后续波次）。 */
export const PAGE_CTX = {};

/* 注册表查询（未登记页返回 null，node 结构钉可测）：palette 刷新与
   showPage 离页收束共用同一查询面。 */
export function pageContextFor(v) {
  return Object.prototype.hasOwnProperty.call(PAGE_CTX, v) ? PAGE_CTX[v] : null;
}

export function showPage(v) {
  const prev = getActiveView();
  if (prev !== v) {
    const prevCtx = pageContextFor(prev);
    if (prevCtx && typeof prevCtx.leave === "function") {
      // 离页收束先于激活（#105 best-effort：leave 异常不阻切页）
      try { prevCtx.leave(); } catch { /* 收束失败静默 */ }
    }
  }
  setActiveView(v); // aurora36 W2-B：页面可见语义单源（写入经 context.js 访问器）
  _sseLeavePage(v); // aurora72 A6-A：离页收束 SSE 连接（留档 runId，回页重订阅幂等）
  T.activate(v);
  (VIEWS[v] || VIEWS.dashboard)(S.currentRunId);
}

/* PR-2 命令面板入口：从任意处打开 run 详情（S.currentRunId 单源在本模块）。 */
export function openRun(runId) {
  S.currentRunId = runId;
  /* aurora72 A4-C（R6 审计 R-2）：深链落地——replaceState 不产生历史条目、
     不触 hashchange（与 nav/tools syncToolHash 同款纪律），刷新/分享保持
     run 态；全站 detail 打开点统一走本入口（行点击/调参完成跳转已收编）。 */
  _syncRouteHash("detail", runId);
  showPage("detail");
}

/* ═══ aurora72 A4-C：两级 hash 路由（R6 审计 R-2）══════════════════════
   形态："#/page"（裸页，旧形态零破坏）与 "#/page/<arg>"（参数页；arg 单段
   贪婪取到串尾，decodeURIComponent 非法序列守卫原样返回）。解析单源
   parseRoute（纯函数，node 行为钉可测）；分发策略面在 app.js _applyHash
   （_VALID_PAGES 回落语义保持），参数段经 routeOpen 交 _ROUTE_OPENERS——
   opener 负责页面激活 + 数据拉取 + 空态/错误态（W7-C 面板）。 */

/* 两级解析（纯函数）："#/detail/<id>" → { page:"detail", arg:"<id>" }；
   "#/tools" → { page:"tools", arg:null }；空/非法形态 → null（调用方保持
   现状）。"#/page/"（尾斜杠空参）不匹配 → null，与 toolsDeepLinkKey 同判。 */
export function parseRoute(hash) {
  const m = String(hash || "").match(/^#\/([^/]+)(?:\/(.+))?$/);
  if (!m) return null;
  let arg = null;
  if (m[2] != null) {
    // 非法百分号序列（如 %zz）不抛——原样返回（toolsDeepLinkKey 同款守卫）
    try { arg = decodeURIComponent(m[2]); } catch { arg = m[2]; }
  }
  return { page: m[1], arg };
}

/* 参数页 opener 注册表：新增参数化页面 = 实现带参 opener + 在此登记一行。
   三个 opener 均为本模块函数（函数声明提升，注册表求值时已初始化），无需
   经 initPages 注入。 */
const _ROUTE_OPENERS = {
  detail: (arg) => openRun(arg),
  tools: (arg) => toolsSelectKey(arg),
  campaign: (arg) => openCampaign(arg),
};

/* 注册表查询（纯查询不执行 opener，node 结构钉可测）：页未收参返回 null。 */
export function routeOpenerFor(page) {
  return Object.prototype.hasOwnProperty.call(_ROUTE_OPENERS, page)
    ? _ROUTE_OPENERS[page] : null;
}

/* 分发入口（app.js _applyHash 消费）：命中 opener 执行并返回 true；页未
   收参返回 false（调用方回落裸页 showPage——两级形态对裸页无害降级）。 */
export function routeOpen(page, arg) {
  const op = routeOpenerFor(page);
  if (!op) return false;
  op(arg == null ? "" : String(arg));
  return true;
}

/* 深链 hash 回写（replaceState：不产历史条目、不触 hashchange——不会与
   hashchange 分发互激）。typeof 守卫保 node import 零 DOM 依赖惯例。 */
export function _syncRouteHash(page, arg) {
  const want = "#/" + page + "/" + encodeURIComponent(String(arg));
  if (typeof location !== "undefined" && location.hash !== want)
    history.replaceState(null, "", want);
}

/* 战役仪表盘带参入口（#/campaign/<run_id>）：记待选 run_id 拉起 campaign
   页——列表渲染完成后消费，未命中回落表头（tools 深链同款待选纪律）。 */
let _campaignPendingId = null;
export function openCampaign(runId) {
  _campaignPendingId = String(runId || "");
  showPage("campaign");
}

/* 待选 run_id 消费（pageCampaign 渲染清单后调用）：读取并清零——与拆分前
   模块内 let「消费即清」语义等价（清除动作留在唯一写模块，跨模块只读快照）。 */
export function consumeCampaignPendingId() {
  const v = _campaignPendingId;
  _campaignPendingId = null;
  return v;
}
