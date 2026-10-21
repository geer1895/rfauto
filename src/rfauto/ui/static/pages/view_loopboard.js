/* rfauto 执行看板页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）：
   自治环步骤可视 + 暂停/接管（WP3.5）。
   ═══ 架构批 W1-S3（R6 审计 F-4/R-1）═══ pollBoard/boardBadge 提升到模块
   层（无页内闭包依赖，注册字面与守卫字面不动）；渲染降噪缓存 _lastBoardKey
   + PageContext 增量钩子 loopboardCtx（注册在 pages.js → router.js PAGE_CTX）。
   i18n（架构批 W4-S1 半程收尾全清）：壳/help 块分段 t()、状态行/空态/
   控制 toast 全迁词表（loopboard.* 键域，zh 与旧字面逐字节同、en 新增）——
   拼接数据段（板 id/步骤名/时间戳）照旧 esc 后拼模板，词表值零 HTML；
   公告/toast 走 textContent 单点。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { kitBadge, kitConfirm, kitPanelHead } from "./kit.js";
// i18n（W6-S2 接管确认 + W4-S1 全清）：壳静态标签 data-i18n+首扫；动态容器
// 文案 t() 渲染期烘焙。
import { t, applyI18nRoot } from "./i18n.js";
import { _pollRegister, _pollStop, _pollVisible } from "./polling.js";
// 深链二批（架构批 W2-S5）：#/loopboard/<board_id> 待选消费 + 选中回写 hash
import { _syncRouteHash, consumeLoopBoardPendingId } from "./router.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 3 点）——
// 数据面（2s 轮询看板/看板清单）接 viewSignal("loopboard") 切页收束 + aborted
// 短路（离页在途 tick 不再写隐藏区）；动作面（暂停/接管控制 POST）保持无
// signal（用户动作不被切页取消）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* ── 执行看板（WP3.5 v1.2 增强②）：自治环步骤可视 + 暂停/接管 ────────────
   CLI 批处理 + GUI 观察的折中路线：环进程写 runs/loop_boards/<id>.json，
   本页只读看板 + 下发控制命令（环在步骤边界协作式响应，不打断仿真）。 */

let loopSelected = null;

/* F-4 渲染降噪缓存（R6 审计 F-4，R1 P1-11 清偿）：看板 JSON 空闲期逐字节
   不变（updated_at 仅环侧 _flush 写盘时刷新，read_board 原样回读），payload
   序列化串比对命中即跳过五处 innerHTML 重建——此前每 2s 全量重绘里程碑+
   步骤两表（文本选区打断+闪烁根因）。键含 board_id：换看板自然失效；控制
   命令/环推进改变 payload 同样失效；错误响应清缓存（恢复后强制重绘）。 */
let _lastBoardKey = null;
/* W5-S23：看板状态变迁公告的记忆面（上一拍状态文本；与 F-4 键缓存同寿命
   语义——错误响应清键时一并归零，恢复后同状态不重复播报由空串初值判定）。 */
let _lastBoardStatus = "";

function boardBadge(s) {
  // A7-A ui-kit：看板状态→类单源（kitBadge 查 KIT_STATUS_CLS；未列状态
  // 一律 muted——原查表回退同串）
  return kitBadge(s || "N/A", s);
}

async function pollBoard() {
  if (!_pollVisible("loopboard")) return; // P2-13：当前页+可见性双守卫（跳过 fetch，定时器保留）
  if (!loopSelected) return;
  const b = await apiFetch("/api/loop/board/" + encodeURIComponent(loopSelected),
    { signal: viewSignal("loopboard") });
  if (b.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  if (!b.ok) {
    T.$("lb-status").textContent = b.error || "";
    _lastBoardKey = null;
    _lastBoardStatus = ""; // W5-S23：错误清状态记忆（恢复后同状态重播报一次）
    return;
  }
  // F-4：payload 无变化跳过渲染（选区/滚动位保持，零闪烁）；五处写面
  // （lb-status/lb-current/两表 tbody/lb-best）全部幂等，跳过=零行为差。
  const key = loopSelected + "\u0000" + JSON.stringify(b);
  if (key === _lastBoardKey) return;
  _lastBoardKey = key;
  T.$("lb-status").innerHTML = boardBadge(b.status);
  // W5-S23（深审 b 面）：看板状态变迁读屏公告——2s 轮询 F-4 去重后，
  // 状态真实变化时经 T.announce 播报一次（公告走自建 live region、零新增
  // DOM 写面——F-4 五写面计数钉保持；T.announce 缺席=异常部署静默，
  // #105 best-effort）。
  if (b.status && b.status !== _lastBoardStatus) {
    try {
      if (typeof T.announce === "function") T.announce(t("loopboard.announce_lead") + b.status);
    } catch { /* 公告面缺席不阻主路径 */ }
    _lastBoardStatus = b.status;
  }
  const cs = b.current_step;
  T.$("lb-current").innerHTML = cs
    ? t("loopboard.current_lead") + `<b>${esc(cs.name)}</b>${cs.milestone ? "（" + esc(cs.milestone) + "）" : ""} · ${esc(cs.detail || "")} · ${esc(cs.at || "")}`
    : t("loopboard.idle_lead") + `${esc(b.recipe || "?")}` + t("loopboard.idle_tail") + `${esc(b.updated_at || "")}`;
  const ms = T.$("lb-ms").querySelector("tbody");
  ms.innerHTML = (b.milestones || []).map((m) =>
    `<tr><td>${esc(m.id)}</td><td>${esc(m.name)}</td><td class='muted'>${esc(m.difficulty)}</td>
     <td class='muted'>${esc(m.acceptance)}${m.detail ? "<br>→ " + esc(m.detail) : ""}</td>
     <td>${boardBadge(m.status)}</td></tr>`).join("")
    || `<tr><td colspan='5' class='muted'>${t("loopboard.no_milestones")}</td></tr>`;
  T.$("lb-best").innerHTML = b.best
    ? `best cost=<b>${(b.best.cost ?? 0).toFixed(4)}</b>` + t("loopboard.best_mid") + `<code>${esc(JSON.stringify(b.best.params || {}))}</code>`
    : (b.summary ? esc(b.summary) : t("loopboard.no_points"));
  const st = T.$("lb-steps").querySelector("tbody");
  st.innerHTML = (b.steps || []).slice(-12).reverse().map((s) =>
    `<tr><td>${esc(s.index)}</td><td>${esc(s.name)}</td><td>${esc(s.milestone || "")}</td>
     <td class='muted'>${s.result ? esc(JSON.stringify(s.result).slice(0, 120)) : esc(s.detail || "")}</td>
     <td class='muted'>${esc(s.at || "")}</td></tr>`).join("")
    || `<tr><td colspan='5' class='muted'>${t("loopboard.no_steps")}</td></tr>`;
}

export async function pageLoopBoard() {
  const v = T.$("view-loopboard");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("loopboard.help_1_lead")}<b>${t("loopboard.help_1_core")}</b>${t("loopboard.help_1_mid")}<b>${t("loopboard.help_1_core2")}</b>${t("loopboard.help_1_tail")}</li>
      <li>${t("loopboard.help_2_lead")}<b>${t("loopboard.help_2_core")}</b>${t("loopboard.help_2_tail")}</li>
      <li><b>${t("loopboard.help_3_core")}</b>${t("loopboard.help_3_tail")}</li>`) +
    `<h2 class='page'><span data-i18n='loopboard.title'>${t("loopboard.title")}</span> <small data-i18n='loopboard.subtitle'>${t("loopboard.subtitle")}</small></h2>
      <div class='panel'><div class='toolbar'>
        ${t("loopboard.board_label")} <select id='lb-id' style='min-width:300px'></select>
        <button class='minor' id='lb-refresh' data-i18n='loopboard.reload'>${t("loopboard.reload")}</button>
        <span id='lb-status'></span>
      </div>
      <div id='lb-current' class='muted' style='margin-top:6px'></div></div>
      ${kitPanelHead(t("loopboard.ms_title"))}
        <table id='lb-ms'><thead><tr><th scope="col">ID</th><th scope="col">${t("loopboard.th_milestone")}</th><th scope="col">${t("loopboard.th_difficulty")}</th><th scope="col">${t("loopboard.th_acceptance")}</th><th scope="col">${t("loopboard.th_status")}</th></tr></thead><tbody></tbody></table></div>
      <div class='panel'><b class='title'>${t("loopboard.control_title")}</b>
        <div class='toolbar'>
          <button class='act' id='lb-pause' data-i18n='loopboard.pause'>${t("loopboard.pause")}</button>
          <button class='minor' id='lb-resume' data-i18n='loopboard.resume'>${t("loopboard.resume")}</button>
          <button class='minor' id='lb-takeover' data-i18n='loopboard.takeover'>${t("loopboard.takeover")}</button>
        </div>
        <div id='lb-best' class='muted' style='margin-top:6px'></div></div>
      <div class='panel'><b class='title'>${t("loopboard.steps_title")}</b>
        <table id='lb-steps'><thead><tr><th scope="col">#</th><th scope="col">${t("loopboard.th_step")}</th><th scope="col">${t("loopboard.th_milestone")}</th><th scope="col">${t("loopboard.th_detail")}</th><th scope="col">${t("loopboard.th_time")}</th></tr></thead><tbody></tbody></table></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W4-S1 全清；幂等，动态容器走 t() 烘焙）
  T.$("lb-refresh").onclick = loadBoards;
  // 深链二批（架构批 W2-S5）：选中回写 hash（replaceState 不触 hashchange）
  const syncLoopHash = () => { if (loopSelected) _syncRouteHash("loopboard", loopSelected); };
  T.$("lb-id").onchange = () => { loopSelected = T.$("lb-id").value || null; syncLoopHash(); pollBoard(); };
  T.$("lb-pause").onclick = () => sendControl("pause");
  T.$("lb-resume").onclick = () => sendControl("resume");
  // W6-S2（R1 P9-8）：接管=破坏性动作（夺环控制权、停自动推进）——
  // kitConfirm 确认闸（危险档）。
  T.$("lb-takeover").onclick = () => kitConfirm({
    title: t("loopboard.takeover"),
    body: t("loopboard.takeover_body"),
    danger: true,
    onOk: () => sendControl("takeover"),
  });
  await loadBoards();
  // 深链二批：#/loopboard/<board_id> 待选消费——清单命中才选中（覆盖
  // loadBoards 的上次选中恢复），未命中回落首项；消费即清（router.js 单源写）。
  const pendingBoard = consumeLoopBoardPendingId();
  if (pendingBoard) {
    const lbSel = T.$("lb-id");
    if ([...lbSel.options].some((o) => o.value === pendingBoard)) {
      lbSel.value = pendingBoard;
      loopSelected = pendingBoard;
    }
  }
  _pollRegister("loopboard", "loopboard", pollBoard, 2000); // P2-13：轮询托管（含进页立即拉一次）
  syncLoopHash(); // 深链二批：初载/深链消费后 hash 对齐（刷新/分享保持所选看板）

  async function loadBoards() {
    const d = await apiFetch("/api/loop/boards",
      { signal: viewSignal("loopboard") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const sel = T.$("lb-id");
    const cur = loopSelected;
    sel.innerHTML = (d.boards || []).map((b) =>
      `<option value="${escAttr(b.board_id)}">${esc(b.board_id)} · ${esc(b.status || "?")} · ${esc(b.recipe || "")}</option>`).join("")
      || `<option value=''>${t("loopboard.no_boards")}</option>`;
    if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
    loopSelected = sel.value || null;
  }

  async function sendControl(action) {
    if (!loopSelected) return T.msg(t("loopboard.select_first"), false);
    const r = await apiFetch("/api/loop/control", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_id: loopSelected, action }),
    });
    T.msg(r.ok ? t("loopboard.control_sent_tpl", { a: action }) : (r.error || t("loopboard.control_failed")),
      !!r.ok);
    pollBoard();
  }
}

/* R-1 PageContext（架构批 W1-S3 试点，增量钩子）：refresh=palette「刷新
   当前页数据」立即拉一次看板（不全量重进重挂轮询）；leave=离页停表（
   _pollStop 非终态并入——fn 保留，重进 _pollRegister 先停旧再挂新；
   _pollVisible 双守卫语义保留，恢复可见复活纪律=test_ui_lifecycle 钉面）。 */
export const loopboardCtx = {
  refresh: () => pollBoard(),
  leave: () => _pollStop("loopboard"),
};
