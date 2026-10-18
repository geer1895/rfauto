/* rfauto 执行看板页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   自治环步骤可视 + 暂停/接管（WP3.5）。
   ═══ aurora72 W1-S3（R6 审计 F-4/R-1）═══ pollBoard/boardBadge 提升到模块
   层（无页内闭包依赖，注册字面与守卫字面不动）；渲染降噪缓存 _lastBoardKey
   + PageContext 增量钩子 loopboardCtx（注册在 pages.js → router.js PAGE_CTX）。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { kitBadge, kitPanelHead } from "./kit.js";
import { _pollRegister, _pollStop, _pollVisible } from "./polling.js";

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
  const b = await T.api("/api/loop/board/" + encodeURIComponent(loopSelected));
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
      if (typeof T.announce === "function") T.announce("执行看板状态：" + b.status);
    } catch { /* 公告面缺席不阻主路径 */ }
    _lastBoardStatus = b.status;
  }
  const cs = b.current_step;
  T.$("lb-current").innerHTML = cs
    ? `当前步骤：<b>${esc(cs.name)}</b>${cs.milestone ? "（" + esc(cs.milestone) + "）" : ""} · ${esc(cs.detail || "")} · ${esc(cs.at || "")}`
    : `配方：${esc(b.recipe || "?")} · 步骤空闲 · 更新于 ${esc(b.updated_at || "")}`;
  const ms = T.$("lb-ms").querySelector("tbody");
  ms.innerHTML = (b.milestones || []).map((m) =>
    `<tr><td>${esc(m.id)}</td><td>${esc(m.name)}</td><td class='muted'>${esc(m.difficulty)}</td>
     <td class='muted'>${esc(m.acceptance)}${m.detail ? "<br>→ " + esc(m.detail) : ""}</td>
     <td>${boardBadge(m.status)}</td></tr>`).join("")
    || "<tr><td colspan='5' class='muted'>无里程碑</td></tr>";
  T.$("lb-best").innerHTML = b.best
    ? `best cost=<b>${(b.best.cost ?? 0).toFixed(4)}</b> · 参数 <code>${esc(JSON.stringify(b.best.params || {}))}</code>`
    : esc(b.summary || "尚无有效评估点");
  const st = T.$("lb-steps").querySelector("tbody");
  st.innerHTML = (b.steps || []).slice(-12).reverse().map((s) =>
    `<tr><td>${esc(s.index)}</td><td>${esc(s.name)}</td><td>${esc(s.milestone || "")}</td>
     <td class='muted'>${s.result ? esc(JSON.stringify(s.result).slice(0, 120)) : esc(s.detail || "")}</td>
     <td class='muted'>${esc(s.at || "")}</td></tr>`).join("")
    || "<tr><td colspan='5' class='muted'>暂无完成步骤</td></tr>";
}

export async function pageLoopBoard() {
  const v = T.$("view-loopboard");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>自验证环（propose→verify→fix + 由易到难里程碑）以批处理方式在 service 层跑，本页<b>观察</b>当前步骤与逐里程碑验收，并可下发 <b>暂停/继续/接管</b>。</li>
      <li>暂停是<b>协作式</b>的：环只在步骤边界响应，不打断进行中的仿真；暂停超时自动续跑（批处理不被无限期挂死）。</li>
      <li><b>接管</b>：环如实停止（verdict=TAKEN_OVER），best-so-far 参数已落沙箱草稿，去「Agent 助手」promote 走三层 Gate 继续生效。</li>`) +
    `<h2 class='page'>执行看板 <small>自治环步骤可视 + 暂停/接管（CLI 批处理 + GUI 观察）</small></h2>
      <div class='panel'><div class='toolbar'>
        看板: <select id='lb-id' style='min-width:300px'></select>
        <button class='minor' id='lb-refresh'>刷新清单</button>
        <span id='lb-status'></span>
      </div>
      <div id='lb-current' class='muted' style='margin-top:6px'></div></div>
      ${kitPanelHead("里程碑（由易到难，逐项验收）")}
        <table id='lb-ms'><thead><tr><th scope="col">ID</th><th scope="col">里程碑</th><th scope="col">难度</th><th scope="col">验收判据</th><th scope="col">状态</th></tr></thead><tbody></tbody></table></div>
      <div class='panel'><b class='title'>控制（环在步骤边界响应）</b>
        <div class='toolbar'>
          <button class='act' id='lb-pause'>⏸ 暂停</button>
          <button class='minor' id='lb-resume'>▶ 继续</button>
          <button class='minor' id='lb-takeover'>✋ 接管</button>
        </div>
        <div id='lb-best' class='muted' style='margin-top:6px'></div></div>
      <div class='panel'><b class='title'>步骤历史</b>
        <table id='lb-steps'><thead><tr><th scope="col">#</th><th scope="col">步骤</th><th scope="col">里程碑</th><th scope="col">详情</th><th scope="col">时间</th></tr></thead><tbody></tbody></table></div>`;
  T.$("lb-refresh").onclick = loadBoards;
  T.$("lb-id").onchange = () => { loopSelected = T.$("lb-id").value || null; pollBoard(); };
  T.$("lb-pause").onclick = () => sendControl("pause");
  T.$("lb-resume").onclick = () => sendControl("resume");
  T.$("lb-takeover").onclick = () => sendControl("takeover");
  await loadBoards();
  _pollRegister("loopboard", "loopboard", pollBoard, 2000); // P2-13：轮询托管（含进页立即拉一次）

  async function loadBoards() {
    const d = await T.api("/api/loop/boards");
    const sel = T.$("lb-id");
    const cur = loopSelected;
    sel.innerHTML = (d.boards || []).map((b) =>
      `<option value="${escAttr(b.board_id)}">${esc(b.board_id)} · ${esc(b.status || "?")} · ${esc(b.recipe || "")}</option>`).join("")
      || "<option value=''>（暂无看板——跑自治环后出现）</option>";
    if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
    loopSelected = sel.value || null;
  }

  async function sendControl(action) {
    if (!loopSelected) return T.msg("先选择看板", false);
    const r = await T.api("/api/loop/control", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_id: loopSelected, action }),
    });
    T.msg(r.ok ? `已下发 ${action}，环在步骤边界响应` : (r.error || "命令失败"),
      !!r.ok);
    pollBoard();
  }
}

/* R-1 PageContext（aurora72 W1-S3 试点，增量钩子）：refresh=palette「刷新
   当前页数据」立即拉一次看板（不全量重进重挂轮询）；leave=离页停表（
   _pollStop 非终态并入——fn 保留，重进 _pollRegister 先停旧再挂新；
   _pollVisible 双守卫语义保留，恢复可见复活纪律=test_ui_lifecycle 钉面）。 */
export const loopboardCtx = {
  refresh: () => pollBoard(),
  leave: () => _pollStop("loopboard"),
};
