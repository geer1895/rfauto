/* rfauto 工作台轮询生命周期托管（aurora_d UI-R2 自 pages.js 拆出，
   aurora36 W2-B 块逐字节搬移）：_pollRegister/_pollStop/_pollVisible +
   标签页可见性暂停/恢复（装配走 initPages 的 _bindVisibilityPolling）。 */

import { T, getActiveView } from "./context.js";

/* P2-13/P0-5（轮询离页空转）：轮询生命周期托管。
   回调先过 _pollVisible（当前页 + document.visibilityState）双守卫——不可
   见跳过 fetch 但定时器保留；标签页隐藏（visibilitychange）暂停定时器，
   恢复可见立即拉一次并重启。终态（如 tune 完成）走 _pollStop(name, true)
   清 fn，恢复逻辑不得复活已终态的轮询。visibilitychange 监听在 initPages
   装配（本模块顶层零 DOM 依赖，node 行为钉 import('./pages.js') 可跑）。 */
const _POLLS = {}; // name → { timer, fn, intervalMs, view }

export function _pollVisible(view) {
  const el = T.$("view-" + view);
  return !!el && el.style.display !== "none" && document.visibilityState !== "hidden";
}

export function _pollStop(name, terminal) {
  const p = _POLLS[name];
  if (!p) return;
  if (p.timer) { clearInterval(p.timer); p.timer = null; }
  if (terminal) p.fn = null; // 终态停：恢复可见不得复活
}

export function _pollRegister(name, view, fn, intervalMs) {
  const p = (_POLLS[name] = _POLLS[name] || { timer: null, fn: null, intervalMs: 0, view: "" });
  _pollStop(name, true); // 重进页面：先彻底停旧（含 fn），再挂新回调
  p.fn = fn; p.intervalMs = intervalMs; p.view = view;
  p.timer = setInterval(fn, intervalMs);
  fn(); // 进页立即拉一次（与原 setInterval + 首拉行为一致）
}

let _visBound = false;
export function _bindVisibilityPolling() {
  if (_visBound || typeof document === "undefined" || !document.addEventListener) return;
  _visBound = true;
  document.addEventListener("visibilitychange", () => {
    for (const p of Object.values(_POLLS)) {
      if (document.visibilityState === "hidden") {
        if (p.timer) { clearInterval(p.timer); p.timer = null; } // 暂停；fn 保留
      } else if (p.fn && !p.timer && getActiveView() === p.view) {
        p.timer = setInterval(p.fn, p.intervalMs);
        p.fn(); // 恢复可见：立即拉一次
      }
    }
  });
}
/* ═══ aurora36 W2-B 生命周期块结束 ═══ */
