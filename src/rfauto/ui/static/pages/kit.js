/* rfauto 工作台 UI-KIT（架构批 UI-R2 自 pages.js 拆出，架构批
   A7-A/A8-A 两块逐字节搬移）：kitTable/kitPanelHead/kitBadge 族 +
   kitSkeleton/kitEmptyState/kitErrorPanel。全部零顶层执行（node 行为钉
   可测）；bindEmptyStates 的空态跳转钮复用 router.showPage 单源。
   i18n（架构批 W2-S1 批 4，R1 §面2 P9-5）：错误/空态三缺省串
   "暂无数据/加载失败/重试" 单源迁 common.empty/load_failed/retry（kit 是
   11 视图的空态/错误态单源，一处迁词表全站受益）——zh 档 t() 返回值与
   旧字面逐字节同（node 行为钉 zh 缺省档复现）；调用方显式传 empty/文案
   的覆盖路径零扰动。 */

import { T } from "./context.js";
import { esc, escAttr } from "./dom.js";
import { t } from "./i18n.js";
import { showPage } from "./router.js";

/* ═══ 架构批 A7-A（R6 审计 R-3 试点）：UI-KIT 三件（表/面板头/状态徽章）═══
   试点策略（R6 R-3）：不全量重构，抽 3 类最高频重复模式做共享层——
   ①kitTable（34 张表同构 thead/tbody/scope/空态壳）②kitPanelHead
   （43 处 <div class='panel'><b class='title'> 面板头壳）③kitBadge 族
   （状态→badge 类映射三元单源）。存量消费点按触点渐进迁移（本批每件
   5-8 个最高价值消费点，逐字节等价迁移——aria/类名/结构不变；引号形态
   /类映射语义有差异的点如实不迁），页面特化形态（convergence 图/3D/SSE）
   零触碰。全部零顶层执行、node 可 import（行为钉 tests/unit/test_ui_kit.py）。 */

/* ── ① 数据表构建器 ─────────────────────────────────────────────────────
   columns=列头文本数组（kit 内部 esc——动态列名安全；传 null 为无表头
   键值表形态 <table><tbody>…</tbody></table>）；
   caption=表格读屏命名（W5-S23，深审 b 面：caption 全站为零的收账起步）——
   经 esc 出 <caption class="sr-only">（视觉隐藏 .sr-only，index.html），
   缺省不产出=既有消费点字节等价钉零扰动；rows+rowHtml=行数据与行渲染器
   （rowHtml(row, i) 返回 <tr>…</tr> 原样串，单元格转义责任在调用方——
   与既有行内模板同责）；
   rowsHtml=预构建行串（迁移存量拼装行用，与 rows/rowHtml 二选一）；
   empty=行集为空时的整行原样串（缺省给统一空态行"暂无数据"；显式传 ""
   保持空 tbody——存量无空态表逐字节等价迁移用；覆盖串引号形态按消费点
   原样保留，如 colspan='4' 单引号点）；
   sortable=true 挂 data-sortable（配合 makeSortable/mountSortableTables）。 */
export function kitTable({ columns, rows, rowHtml, rowsHtml, empty, sortable, caption }) {
  const body = rowsHtml != null ? rowsHtml
    : (rows || []).map(rowHtml || (() => "")).join("");
  if (!columns) return "<table><tbody>" + body + "</tbody></table>";
  const cap = caption ? `<caption class="sr-only">${esc(caption)}</caption>` : "";
  const ths = columns.map((c) => `<th scope="col">${esc(c)}</th>`).join("");
  const nCols = columns.length;
  const emptyRow = empty != null ? empty
    : `<tr><td colspan="${nCols}" class="muted">${t("common.empty")}</td></tr>`;
  return `<table${sortable ? " data-sortable" : ""}>${cap}<thead><tr>${ths}</tr></thead><tbody>` +
    (body || emptyRow) + "</tbody></table>";
}

/* ── ② 面板头构建器 ─────────────────────────────────────────────────────
   <div class='panel'[ attrs]><b class='title'>TITLE</b>ACTIONS 壳单源。
   title=预构建标题 HTML（动态值调用方先 esc——与既有内联模板同责，kit 不
   二次转义避免双重转义）；actions=标题后原样续串（控件/正文/换行按调用方
   原字节保留，缺省空）；attrs=panel 开标签上的原样属性串（style/id 等，
   引号形态随消费点原样透传）。工具条形态（<div class='toolbar'><b>…）与
   b 带属性变体（<b id=…>）不在此壳内——逐字节不等，如实不迁。 */
export function kitPanelHead(title, actions, attrs) {
  return `<div class='panel'${attrs ? " " + attrs : ""}><b class='title'>${title}</b>${actions || ""}`;
}

/* ── ③ 状态→徽章单源 ───────────────────────────────────────────────────
   KIT_STATUS_CLS=全站状态→badge 类映射单源（收敛散落的 ? "ok" : "err" 三
   元；键值按既有各点口径逐一登记，未列状态一律 muted——与 board/锚表回退
   口径同）。注意两处既有语义与此表不同、如实不迁：runs 表状态列恒 muted
   淡显（语义=次要信息非状态灯）、queue 阶段徽章 done/pending 之外一律
   err（含 running——与本表 running:muted 冲突）。
   渲染单点仍走 T.badge（app.js badge 内部 esc，AU-4 单点转义不复制）；
   T 缺席（node 行为钉/独立加载）回退 _kitBadgeRaw——与 T.badge 逐字节同
   串的本地实现，仅测试/降级语境生效。 */
const KIT_STATUS_CLS = {
  // 判定族（校准 verdict / 战役 verdict / 报告类别）
  PASS: "ok", FAIL: "err", COMPLETE: "ok", ABORTED: "err",
  sim_ci: "warn", calibration: "ok",
  // run/阶段状态族（done 族绿；fail 族红；中间态灰；暂停族黄）
  done: "ok", passed: "ok", pass: "ok",
  fail: "err", failed: "err", solve_failed: "err", taken_over: "err",
  running: "muted", pending: "muted", other: "muted",
  paused: "warn", pause_requested: "warn",
  // 锚状态族
  active: "ok", stale: "warn", experimental: "warn",
  retired: "muted", awaiting_data: "muted",
};
export function kitBadgeCls(status) {
  return Object.prototype.hasOwnProperty.call(KIT_STATUS_CLS, status)
    ? KIT_STATUS_CLS[status] : "muted";
}
function _kitBadgeRaw(text, cls) {
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}
function _kitBadgeEl(text, cls) {
  return T.badge ? T.badge(text, cls) : _kitBadgeRaw(text, cls);
}
/* 按状态查类渲染（text=徽章文本，status=查表键）。 */
export function kitBadge(text, status) {
  return _kitBadgeEl(text, kitBadgeCls(status));
}
/* 二元判定徽章：PASS→ok 绿，其余一律 FAIL/err（校准/P0 gate 既有口径）；
   label 缺省 PASS/FAIL 字面，传参覆盖（如 "ρ=0.9 PASS"）。 */
export function kitVerdictBadge(verdict, label) {
  return verdict === "PASS"
    ? _kitBadgeEl(label || "PASS", "ok")
    : _kitBadgeEl(label || "FAIL", "err");
}
/* 布尔可用性徽章：true→ok 绿/false→err 红（求解器可用/不可用族）。 */
export function kitBoolBadge(ok, yes, no) {
  return _kitBadgeEl(ok ? yes : no, ok ? "ok" : "err");
}
/* ═══ 架构批 A7-A UI-KIT 块结束 ═══ */

/* ═══ 架构批 A8-A（R6 审计 P-2/P-3/P-4 打磨批）：kit 五件 ═══
   ①kitSkeleton 骨架占位条 ②kitSkeletonRows 表体骨架行（数据首拉占位，
   reduced-motion 降级=静态灰块，见 index.html .skeleton 块）③kitEmptyState
   空态三件式（图标+一句话+下一步动作钮）④bindEmptyStates 空态跳转钮接线
   ⑤kitErrorPanel 错误态动作化（badge+错误串+重试钮，W7-C detail 内联面板
   模式推广到高频 API 失败点）。全部纯字符串构建、零顶层 DOM 执行（node
   行为钉可测）；DOM 接线只在 bindEmptyStates（显式传入容器才触碰 DOM，
   node 语境 document 守卫直接返回——与 _syncRouteHash 同款守卫）。 */

/* ① 骨架占位条：n 条，宽度按档轮替出有机感。shimmer 纯 CSS：
   .skeleton::after 高光带 translateX 扫过（仅 transform，§7.2 合规）。 */
const _SKEL_WIDTHS = [92, 76, 84, 64, 88, 70];
export function kitSkeleton(n) {
  const count = Math.max(1, Number(n) > 0 ? Math.floor(Number(n)) : 3);
  const out = [];
  for (let i = 0; i < count; i++)
    out.push(`<div class="skeleton" style="width:${_SKEL_WIDTHS[i % _SKEL_WIDTHS.length]}%"></div>`);
  return out.join("");
}

/* ② 表体骨架行：rows 行 × cols 列，每格一条骨架条（首拉表体占位——
   注意结果是 <tr>…</tr> 串，只能放进 tbody，不能放普通容器）。 */
export function kitSkeletonRows(rows, cols) {
  const nR = Math.max(1, Number(rows) > 0 ? Math.floor(Number(rows)) : 4);
  const nC = Math.max(1, Number(cols) > 0 ? Math.floor(Number(cols)) : 1);
  const out = [];
  for (let r = 0; r < nR; r++) {
    let tds = "";
    for (let c = 0; c < nC; c++)
      tds += `<td><div class="skeleton" style="width:${_SKEL_WIDTHS[(r + c) % _SKEL_WIDTHS.length]}%"></div></td>`;
    out.push(`<tr>${tds}</tr>`);
  }
  return out.join("");
}

/* ③ 空态三件式：icon（Unicode 徽标，与 nav .ico 同语言；aria-hidden 装饰性）
   + text 一句话 + cta 下一步动作钮。cta={label,view}（页跳转钮，配 ④ 接线）
   或 {label,id}（自定义动作钮，调用方自行 onclick——如"启动调参"转触既有钮）。
   text 为开发侧 UI 文案（trusted，调用方对动态数据先 esc——与 help() 同责）；
   无 cta 只出图标+句。 */
export function kitEmptyState(text, cta) {
  let btn = "";
  if (cta && cta.label) {
    btn = cta.view != null
      ? `<button class="minor" data-empty-view="${escAttr(cta.view)}">${esc(cta.label)}</button>`
      : `<button class="minor" id="${escAttr(cta.id || "")}">${esc(cta.label)}</button>`;
  }
  return `<div class="empty-state"><span class="empty-ico" aria-hidden="true">${(cta && cta.icon) || "◌"}</span>` +
    `<span class="empty-txt">${text}</span>${btn}</div>`;
}

/* ④ 空态动作接线：容器内全部 [data-empty-view] 钮 → showPage(view)。
   innerHTML 赋值后调用；重复调用幂等（覆盖式 onclick）。 */
export function bindEmptyStates(root) {
  if (typeof document === "undefined" || !root) return;
  root.querySelectorAll("[data-empty-view]").forEach((btn) => {
    btn.onclick = () => showPage(btn.getAttribute("data-empty-view"));
  });
}

/* ⑤ 错误态动作化：badge+错误串+可选重试钮一行式（msg 经 esc 单点转义；
   重试钮由调用方按 id 接线——结构与 W7-C detail 内联面板同构）。 */
export function kitErrorPanel(msg, retryId) {
  return `<div class="err-panel"><span class="badge err">${t("common.load_failed")}</span>` +
    ` <span class="muted">${esc(msg == null ? "" : String(msg))}</span>` +
    (retryId ? ` <button class="minor" id="${escAttr(retryId)}">${t("common.retry")}</button>` : "") + `</div>`;
}
/* ═══ 架构批 A8-A kit 五件结束 ═══ */

/* ═══ 架构批 UI-R4（A6 审查 P1-5 全域清偿）：kitClickRow 可点行统一形态 ═══
   行点击（clickRow 式）交互的键盘可达单源。改造站点 12 处（台账见
   tests/unit/test_ui_a11y_rows.py）：dashboard 活动流/最近 Run、runs 表、
   datasets、anchors、UQ 资产、配方目录、校准、报告清单、queue 决策日志、
   文件浏览器行 + Run 详情可点曲线图。三件：
   ①kitClickRowAttrs——行开标签属性串（innerHTML 模板用）：role +
     tabindex="0" + aria-label。role 缺省 "button"（div 行选择/导航语义；
     Enter+Space 双激活键与 button 惯例一致）；tr 行传 role:null 保表格
     row/cell 语义（role=button 会把行后代降级 presentational 毁表结构——
     可达性靠 tabindex+aria-label+键盘激活达成，不覆写行语义）；
   ②kitApplyClickRowAttrs——DOM 侧同源（createElement 行用，setAttribute
     逐键同口径；setAttribute 字面量语境无需转义）；
   ③bindClickRows——DOM 接线：click 与 Enter/Space 触发同一 onActivate(row)
     （preventDefault 防空格滚屏与锚点 href='#' 页顶跳动——A6 P1-5 对
     queue 决策日志锚的指控点）。
   focus-visible 焦点环零新 CSS：index.html 全局 :focus-visible（PR-1 钉）
   对 [tabindex] 同样生效。零顶层 DOM 执行（node 行为钉可测）；
   bindClickRows 不持 document 引用——querySelectorAll 由 root 提供
   （node 语境传最小 root 桩即可真执行，行为钉无需 jsdom）。 */
export function kitClickRowAttrs(opts) {
  const role = opts && "role" in opts ? opts.role : "button";
  const parts = [];
  if (role) parts.push(`role="${role}"`);
  parts.push('tabindex="0"');
  if (opts && opts.label)
    parts.push(`aria-label="${escAttr(String(opts.label))}"`);
  return parts.join(" ");
}
export function kitApplyClickRowAttrs(el, opts) {
  const role = opts && "role" in opts ? opts.role : "button";
  if (role) el.setAttribute("role", role);
  el.setAttribute("tabindex", "0");
  if (opts && opts.label) el.setAttribute("aria-label", String(opts.label));
  return el;
}
export function bindClickRows(root, onActivate, selector) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll(selector || "[data-kit-click-row]").forEach((row) => {
    row.onclick = () => onActivate(row);
    row.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(row); }
    };
  });
}
/* ═══ 架构批 UI-R4 kitClickRow 块结束 ═══ */

/* ═══ 架构批 W6-S2（R1 审计 P9-8 / R2 Top10 #6 遗产照搬）：kitConfirm ═══
   破坏性动作确认模态（实证痛点：清空对话/接管环控制此前单击即发零确认
   零撤销）。两件：
   ①kitConfirmHtml——纯串构建（node 行为钉可测）：面板壳（标题/正文/取消/
     确认钮，data-act 接线锚）；danger=true 确认钮红档（--err 令牌内联，
     零新 CSS）。title/body/覆盖钮面=调用方 t() 烘焙串，按 kitEmptyState
     text 同责（trusted 开发侧文案，动态数据调用方先 esc）。
   ②kitConfirm——DOM 接线（浏览器）：遮罩底 var(--backdrop-dim)+
     var(--z-modal)（fileBrowser 同款令牌），焦点陷阱三件套照 filebrowser.js
     先例（打开前焦点存根/Tab 首尾回绕/Esc 关闭+关闭还焦）；确认=先关后
     onOk（onOk 异常吞掉不阻关闭——#105 best-effort）；初始焦点落取消钮
     （危险动作缺省安全档）。无 document（node 行为钉/裸环境）返回 null。
   接线点（本批两处）：view_agent 清空对话 / view_loopboard 接管。 */

/* 确认面板串（缺省钮面 common.confirm/common.cancel——kit 是共享组件
   单源，与 common.empty/load_failed/retry 同通道）。 */
export function kitConfirmHtml({ title, body, danger, okLabel, cancelLabel }) {
  const ok = okLabel || t("common.confirm");
  const cancel = cancelLabel || t("common.cancel");
  const okStyle = danger ? ' style="background:var(--err);border-color:var(--err)"' : "";
  return `<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;width:420px;max-width:92vw;padding:14px">` +
    `<b class="title">${title == null ? "" : title}</b>` +
    `<div class="muted" style="margin:var(--space-2) 0 var(--space-3)">${body == null ? "" : body}</div>` +
    `<div class="toolbar" style="justify-content:flex-end;margin:0">` +
    `<button class="minor" data-act="cancel">${esc(cancel)}</button>` +
    `<button class="act"${okStyle} data-act="ok">${esc(ok)}</button>` +
    `</div></div>`;
}

/* 确认模态接线（返回 backdrop 元素便于测试/诊断；node 环境返回 null）。 */
export function kitConfirm(opts) {
  if (typeof document === "undefined" || !document.body) return null;
  const modal = document.createElement("div");
  modal.className = "kit-confirm";
  modal.setAttribute("role", "dialog"); // PR-1 a11y：模态弹层语义（fileBrowser 同款）
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", String((opts && opts.title) || ""));
  modal.style.cssText = "position:fixed;inset:0;background:var(--backdrop-dim);z-index:var(--z-modal);display:flex;align-items:center;justify-content:center";
  modal.innerHTML = kitConfirmHtml(opts || {});
  document.body.appendChild(modal);
  // 焦点陷阱三件套（filebrowser.js:33-40 先例）
  const savedFocus = document.activeElement;
  const close = () => {
    modal.remove();
    if (savedFocus && document.contains(savedFocus) &&
        typeof savedFocus.focus === "function")
      savedFocus.focus(); // 焦点陷阱③：关闭还焦
  };
  modal.querySelector('[data-act="cancel"]').onclick = close;
  modal.querySelector('[data-act="ok"]').onclick = () => {
    close();
    try {
      if (opts && typeof opts.onOk === "function") opts.onOk();
    } catch { /* #105：确认回调异常不阻模态收束 */ }
  };
  modal.onclick = (e) => { if (e.target === modal) close(); };
  modal.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") {
      // 焦点陷阱②：Tab 首尾回绕（弹层内可聚焦元素循环，不逃出模态）
      const focusables = [...modal.querySelectorAll(
          "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
        .filter((el) => el.offsetParent !== null);
      e.preventDefault();
      if (!focusables.length) return;
      const idx = focusables.indexOf(document.activeElement);
      const next = idx === -1
        ? (e.shiftKey ? focusables[focusables.length - 1] : focusables[0])
        : (e.shiftKey
          ? focusables[(idx - 1 + focusables.length) % focusables.length]
          : focusables[(idx + 1) % focusables.length]);
      next.focus();
    }
  });
  // 初始焦点落取消钮（破坏性确认缺省安全档——回车误发不打红）
  const cancelBtn = modal.querySelector('[data-act="cancel"]');
  if (cancelBtn) cancelBtn.focus({ preventScroll: true });
  return modal;
}
/* ═══ 架构批 W6-S2 kitConfirm 块结束 ═══ */
