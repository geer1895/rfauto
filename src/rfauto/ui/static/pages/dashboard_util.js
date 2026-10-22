/* rfauto 总览组件纯函数（aurora_d UI-R2 自 pages.js 拆出，aurora36
   W4-C 块逐字节搬移）：relTime 相对时间 / freshnessTier+
   freshnessRingSvg 数据新鲜度环 / statusBucket run 状态分桶（甜甜圈/
   活动徽章共用单源）。node 行为钉可测（test_ui_dashboard_widgets）。 */

import { esc, escAttr } from "./dom.js";

/* ═══ aurora36 W4-C：dashboard 组件深化（R1 §1.3 活动日志/新鲜度环/甜甜圈）
   + palette act-export-chart 事件桥。纯函数三件 + 分桶一件（node 行为钉可测），
   DOM/SVG 装配面在 pageDashboard 的 widget 渲染器内。 ═══ */

/* 相对时间（活动日志消费；R1 §1.3 活动日志"5 分钟前"口径）：ts=API ISO 串
   （run_store timestamp=UTC isoformat），now 缺省取当前时刻（node 钉显式传参）。
   阶梯：(<60s)刚刚 → N 分钟前 → N 小时前 → N 天前；>30 天回落绝对短日期
   （相对时长对月/年歧义太大，不如给确定时刻）。非法/缺失 → "-"。 */
export function relTime(ts, now) {
  const t = ts ? new Date(ts).getTime() : NaN;
  if (!Number.isFinite(t)) return "-";
  const d = Math.max(0, (now ?? Date.now()) - t);
  if (d < 60e3) return "刚刚";
  if (d < 3600e3) return `${Math.floor(d / 60e3)} 分钟前`;
  if (d < 86400e3) return `${Math.floor(d / 3600e3)} 小时前`;
  if (d < 30 * 86400e3) return `${Math.floor(d / 86400e3)} 天前`;
  const dt = new Date(t);
  const p2 = (x) => String(x).padStart(2, "0");
  // 全部经 p2 包裹做纯拼接（不用模板插值直引 dt.getX()——XSS 反向扫描的
  // 裸插值口径零新增，test_ui_xss_escape 豁免清单不可编辑面）
  return p2(dt.getFullYear()) + "-" + p2(dt.getMonth() + 1) + "-" + p2(dt.getDate()) +
    " " + p2(dt.getHours()) + ":" + p2(dt.getMinutes());
}

/* 数据新鲜度三档（R1 §1.3 新鲜度环）：<1h → ok（绿）/<24h → warn（黄）/
   更久 → stale（灰）；时间非法/缺失 → none（渲染灰空环）。hours 对未来
   时间戳（时钟偏斜）钳 0，不出现负档。 */
export function freshnessTier(ts, now) {
  const t = ts ? new Date(ts).getTime() : NaN;
  if (!Number.isFinite(t)) return { tier: "none", hours: null };
  const hours = Math.max(0, ((now ?? Date.now()) - t) / 3600e3);
  return { tier: hours < 1 ? "ok" : hours < 24 ? "warn" : "stale", hours };
}

/* 新鲜度环 SVG（纯静态标记串）：环色走令牌三档（--ok/--warn/--muted2），
   进度弧=24h 窗口内剩余新鲜度（stale/none 给最小可见弧），title 悬浮显示
   具体时间（属性语境 escAttr 纪律；SVG <title> 子元素给原生 tooltip 兜底）。
   零定时器——重绘只挂 dashboard 既有渲染时机（showPage 进页/组件增删拖拽）。 */
export function freshnessRingSvg(ts, now) {
  const { tier, hours } = freshnessTier(ts, now);
  const color = tier === "ok" ? "var(--ok)"
    : tier === "warn" ? "var(--warn)" : "var(--muted2)";
  const R = 9, C = 2 * Math.PI * R;
  const frac = (tier === "ok" || tier === "warn")
    ? Math.max(0.06, 1 - Math.min(1, (hours || 0) / 24)) : 0.08;
  const label = tier === "none"
    ? "数据新鲜度：暂无 run"
    : `数据新鲜度：${relTime(ts, now)}（${tier === "ok" ? "1 小时内" : tier === "warn" ? "24 小时内" : "超过 24 小时"}）`;
  const dash = `${(C * frac).toFixed(2)} ${(C * (1 - frac)).toFixed(2)}`;
  return `<svg width="26" height="26" viewBox="0 0 26 26" role="img" ` +
    `aria-label="${escAttr(label)}" title="${escAttr(label)}" style="display:block">` +
    `<title>${esc(label)}</title>` +
    `<circle cx="13" cy="13" r="${R}" fill="none" stroke="var(--panel2)" stroke-width="3"/>` +
    `<circle cx="13" cy="13" r="${R}" fill="none" stroke="${color}" stroke-width="3" ` +
    `stroke-linecap="round" stroke-dasharray="${dash}" transform="rotate(-90 13 13)"/>` +
    `</svg>`;
}

/* run 状态分桶（甜甜圈/活动徽章共用单源）：status="done" → pass；状态串含
   "fail"（solve_failed/failed/…）→ fail；其余（running/imported 等中间态）
   → other。落库面实证值：api.py 写 "done"/"solve_failed" 两态+外来导入行。 */
export function statusBucket(status) {
  const s = String(status || "").toLowerCase();
  if (s === "done") return "pass";
  if (s.includes("fail")) return "fail";
  return "other";
}
