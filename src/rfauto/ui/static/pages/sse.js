/* rfauto 工作台 SSE 实时面（架构批 UI-R2 自 pages.js 拆出，
   架构批 A6-A 块逐字节搬移）：帧分派/回退判定/URL 构造纯函数（node
   行为钉）+ EventSource 订阅/收束/恢复连接管理（渐进增强，零硬依赖）。
   帧形态与消费纪律详见块首注释（server P-1 桥契约）。 */

import { getActiveView } from "./context.js";

/* ═══ 架构批 A6-A（R6 审计 F-1）：SSE 实时面（P-1 桥消费，渐进增强）═════
   server.py /api/runs/{run_id}/events/stream（P-1 桥）帧形态：named 事件
   event=<event_type>（值域=core/events.py EventType，见 _SSE_EVENT_TYPES）+
   id=<event_id> + data=事件 JSON；控制帧 end（data.terminal=true=终态
   run_completed/run_failed 已见 / data.exists=false=run 无事件流）与
   error（服务端读面故障）发出后服务端收束连接；ping=15s 心跳帧；服务端
   1s 增量轮询 events.jsonl、300s 长空闲主动断流——靠浏览器 EventSource
   自动重连续传（服务端无状态，重连后从头重放；消费动作是幂等整页刷新，
   重放无碍）；sse-starlette 缺装端点回 503 JSON 信封（走 onerror 路径）。
   注意：现网并非每个 run 都有 events.jsonl（写入方在编排侧按需落盘），
   空流 exists=false→end 是常态之一——按"暂无事件流"处理（会话内不热重试、
   回页/恢复可见各重试一次），不当错误也不得假称必然自动刷新（文案同口径）。
   消费纪律（渐进增强，零硬依赖——F-1 改法）：
   - 只接最有价值两面：tune（trial 推送期 3s 轮询回调守卫跳过降负载）与
     campaign（选 run 即订阅进度流，兑现自动刷新承诺）；
   - onopen → live=true：轮询回调经 ssePollSuppressed 跳过 fetch（定时器
     保留，setInterval 计数不变——w7c 跨席计数钉口径）；流未开/已断期间
     轮询照常执行 → 回退链天然成立；
   - 原生连接错误（断线/503，plain Event 无 data）即翻 live=false 让轮询
     接管兜底（重连间隙不留新鲜度空窗），连续 _SSE_MAX_ERRORS 次未恢复
     （sseShouldGiveUp，onopen 归零）→ close 放弃、轮询常驻——放弃置
     gaveUp 标记（A6 P1-4）：轮询驱动的重订阅不得复活（旧实现无标记，
     3s 轮询 tick 反复重启注定失败的 EventSource 成重连永动机）；显式
     重连入口才重置=回页新闭包/换 runId（_sseSubscribe 新建状态对象）、
     或 _sseOpen 显式重开（恢复可见对 gaveUp 不放行，与 done 同款不复活）；
   - end 帧经 sseEndMark 分型（terminal=true→done 终态不复活；exists=false
     →empty 暂无事件流、回页/恢复可见重试）与服务端 error 帧（MessageEvent
     有 data，服务端已收流）→ close + 末次刷新收尾（错误经既有数据路径
     可见化，终态语义由消费函数自判，与轮询终态路径同款）；
   - 离页（showPage 切走）与标签页隐藏（visibilitychange）→ close（复用
     W2-B 可见性语义）；回页/恢复可见 _sseResume 重开（runId/refresh 留档）；
   - EventSource 缺席（node import/老浏览器）全链路静默跳过。
   帧分派/回退判定/URL 构造抽纯函数（本块尾部 export），node 行为钉实测
   （tests/unit/test_ui_sse.py）；连接装配面走源码钉。 */
const _SSE_MAX_ERRORS = 3;
/* 订阅事件面（named 帧；server P-1 桥透传 events.jsonl 的 event_type 值域
   ——core/events.py EventType 全 16 值；end/error 为桥控制帧不在值域）。
   run_completed/run_failed 帧本身也触发刷新（kick），随后 end 帧收束。 */
const _SSE_EVENT_TYPES = [
  "run_created", "run_started", "run_completed", "run_failed",
  "trial_started", "trial_completed", "trial_failed",
  "solve_started", "solve_completed", "build_completed", "cache_hit",
  "self_heal", "warning", "progress", "license_wait", "user_cancel",
];
export const _SSE = {}; // name → { es, runId, view, live, errors, refresh, timer, done, empty, gaveUp }

function _sseSupported() {
  return typeof window !== "undefined" && typeof window.EventSource === "function";
}

/* 订阅/换订：幂等键=同 runId 且同 refresh 闭包（同页面会话）——重复进页/
   推送期刷新不重连；refresh 闭包变化=页面重建（同页重进 nav 再点/hash 同页
   亦然），旧闭包渲染打进已脱离 DOM，必须换订新会话。终态收束（done）会话
   内不复活；空流（empty）会话内不热重试；放弃态（gaveUp，A6 P1-4）同会话
   内订阅不得复活——三者经 sseSubscribeBlocked 纯函数门（node 行为钉）；
   回页=新闭包、恢复可见=显式重试点，两者放行（gaveUp 不在恢复放行面：
   放弃后轮询常驻，显式重连入口=回页新闭包/换 runId 才重置）；
   换 runId → 先 close 旧流再开新。refresh=幂等整页刷新。 */
export function _sseSubscribe(name, runId, refresh, view) {
  if (!_sseSupported() || !runId) return;
  if (sseSubscribeBlocked(_SSE[name], runId, refresh)) return; // 幂等门（存活/终态/空流/放弃态）
  _sseClose(name);
  const st = (_SSE[name] = { es: null, runId, view, live: false, errors: 0, refresh, timer: null, gaveUp: false });
  _sseOpen(name, st);
}

function _sseOpen(name, st) {
  const es = new window.EventSource(sseStreamUrl(st.runId));
  st.es = es;
  st.errors = 0;
  st.done = false;
  st.empty = false;
  st.gaveUp = false; // 显式重开=重连入口：清放弃标记（A6 P1-4）
  es.onopen = () => { st.live = true; st.errors = 0; }; // 流可达：轮询让位（守卫跳过）
  es.onmessage = () => _sseKick(name, st); // 无事件名缺省帧（桥缺省 progress 类）
  for (const et of sseSubscribedTypes()) es.addEventListener(et, () => _sseKick(name, st));
  es.addEventListener("end", (e) => { // 终态/空流控制帧：收束 + 末次刷新（跑完面板/座位表落定）
    const refresh = st.refresh;
    const mark = sseEndMark(e && e.data);
    _sseClose(name);
    st.done = mark.done;
    st.empty = mark.empty;
    if (refresh) refresh();
  });
  es.addEventListener("error", (e) => {
    if (e && typeof e.data === "string") { // 服务端 error 帧（MessageEvent）：读面故障，服务端已收流
      const refresh = st.refresh;
      _sseClose(name);
      if (refresh) refresh(); // 回退轮询/手动面，错误经既有数据路径可见化
      return;
    }
    // 原生连接错误（plain Event，无 data）：断线重连中/503——先翻 live=false
    // 让轮询立即接管兜底（不留重连间隙的新鲜度空窗），连续 _SSE_MAX_ERRORS
    // 次未恢复（onopen 归零=「连续」语义）或浏览器已判死（CLOSED）→ 置
    // gaveUp 放弃态（A6 P1-4：轮询常驻，同会话订阅不得复活——轮询驱动的
    // _sseSubscribe 经 sseSubscribeBlocked 门跳过，不再重启注定失败的流）。
    st.live = false;
    if (es.readyState === window.EventSource.CLOSED ||
        sseShouldGiveUp(st.errors + 1, _SSE_MAX_ERRORS)) {
      st.gaveUp = true;
      _sseClose(name);
    } else st.errors += 1;
  });
}

/* 事件帧 → 合并刷新：150ms 去抖（服务端重连重放/批量 trial 事件只刷一次）。 */
function _sseKick(name, st) {
  if (st.timer) return; // 已有待刷
  st.timer = setTimeout(() => {
    st.timer = null;
    if (st.refresh) st.refresh();
  }, 150);
}

function _sseClose(name) { // 收束连接（runId/refresh 留档供回页 _sseResume 重开）
  const st = _SSE[name];
  if (!st) return;
  if (st.timer) { clearTimeout(st.timer); st.timer = null; }
  if (st.es) { try { st.es.close(); } catch { /* 连接已死等，best-effort */ } st.es = null; }
  st.live = false;
}

/* 离页（showPage 单源消费）：切走的视图订阅收束——连接面不跨页存活。 */
export function _sseLeavePage(v) {
  for (const name of Object.keys(_SSE)) {
    if (_SSE[name].view !== v) _sseClose(name);
  }
}

/* 恢复可见（visibilitychange/回页）：view 仍激活且有留档 runId 的订阅重开
   （终态 done 不复活——W2-B "恢复逻辑不得复活已终态" 同款；放弃态 gaveUp
   同款不复活（A6 P1-4：放弃后轮询常驻）；empty 空流是显式重试点：清标记
   探测一次，仍无事件流则重新置 empty）。 */
function _sseResume() {
  if (!_sseSupported()) return;
  for (const [name, st] of Object.entries(_SSE)) {
    if (st.runId && st.refresh && !st.es && !st.done && !st.gaveUp &&
        getActiveView() === st.view &&
        document.visibilityState !== "hidden") {
      st.empty = false;
      _sseOpen(name, st);
    }
  }
}

let _sseVisBound = false;
export function _bindVisibilitySSE() { // A6-A：标签页隐藏收束 SSE 连接（W2-B 同款语义），恢复可见重开
  if (_sseVisBound || typeof document === "undefined" || !document.addEventListener) return;
  _sseVisBound = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      for (const name of Object.keys(_SSE)) _sseClose(name);
    } else _sseResume();
  });
}

/* ── A6-A 纯函数（node 行为钉；无 DOM/工具集依赖）── */

/* 流 URL（同源相对路径；runId 一律 encodeURIComponent——"/"、"\\" 等永
   不进路径段，服务端 run_id 清洗与路由段匹配双保险）。 */
export function sseStreamUrl(runId) {
  return "/api/runs/" + encodeURIComponent(String(runId)) + "/events/stream";
}

/* 订阅事件面（防御性副本；end/error 控制帧不在内——它们走专用监听）。 */
export function sseSubscribedTypes() {
  return _SSE_EVENT_TYPES.slice();
}

/* 帧事件名 → 前端动作（F-1 分派单源）：end=终态收束；error=服务端读面
   故障帧（回退）；其余 EventType 值/缺省帧=合并刷新。未知事件名按刷新
   处理（向前兼容新事件类型，多刷无害）。 */
export function sseFrameAction(eventType) {
  const t = String(eventType == null ? "" : eventType);
  if (t === "end") return "end";
  if (t === "error") return "fallback";
  return "refresh";
}

/* end 控制帧 → 收束标记（纯函数，node 行为钉）：terminal=true→done（终态，
   不复活）；exists=false→empty（该 run 暂无事件流，会话内不热重试）；数据
   异常/缺省按 empty（保守可重试——多一次探测请求无害，错判终态会丢刷新）。 */
export function sseEndMark(rawData) {
  try {
    const d = JSON.parse(typeof rawData === "string" && rawData ? rawData : "{}");
    if (d && d.terminal === true) return { done: true, empty: false };
    if (d && d.exists === false) return { done: false, empty: true };
  } catch { /* 非法 JSON：保守可重试 */ }
  return { done: false, empty: true };
}

/* 回退链判定：连续失败达上限（或调用方传已 CLOSED 形态）→ 放弃 SSE 回退
   轮询。errors 在成功 onopen 时归零——"连续"语义。 */
export function sseShouldGiveUp(errors, maxErrors) {
  return Number(errors) >= Number(maxErrors);
}

/* 订阅幂等门（纯函数，node 行为钉）：同会话（同 runId+同 refresh 闭包）且
   处于存活/终态/空流/放弃态之一 → 跳过重订阅。gaveUp 是 A6 P1-4 的核心面：
   give-up 后轮询每 3s tick 反复调用 _sseSubscribe，无此标记会不断重启注定
   失败的 EventSource（重连永动机）；换 runId/换闭包（回页重建）不拦——
   那是显式重连入口，经 _sseSubscribe 新建状态对象天然重置全部标记。 */
export function sseSubscribeBlocked(cur, runId, refresh) {
  return !!(cur && cur.runId === runId && cur.refresh === refresh &&
    (cur.es || cur.done || cur.empty || cur.gaveUp));
}

/* 轮询让位守卫（pollTune 消费）：SSE 流活跃时轮询回调跳过 fetch——定时器
   保留（setInterval 计数不变），live 翻 false（断流/收束）即自然回退。 */
export function ssePollSuppressed(st) {
  return !!(st && st.live === true);
}
