/* rfauto 执行看板页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   自治环步骤可视 + 暂停/接管（WP3.5）。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { kitBadge, kitPanelHead } from "./kit.js";
import { _pollRegister, _pollVisible } from "./polling.js";

/* ── 执行看板（WP3.5 v1.2 增强②）：自治环步骤可视 + 暂停/接管 ────────────
   CLI 批处理 + GUI 观察的折中路线：环进程写 runs/loop_boards/<id>.json，
   本页只读看板 + 下发控制命令（环在步骤边界协作式响应，不打断仿真）。 */

let loopSelected = null;

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

  function boardBadge(s) {
    // A7-A ui-kit：看板状态→类单源（kitBadge 查 KIT_STATUS_CLS；未列状态
    // 一律 muted——原查表回退同串）
    return kitBadge(s || "N/A", s);
  }

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

  async function pollBoard() {
    if (!_pollVisible("loopboard")) return; // P2-13：当前页+可见性双守卫（跳过 fetch，定时器保留）
    if (!loopSelected) return;
    const b = await T.api("/api/loop/board/" + encodeURIComponent(loopSelected));
    if (!b.ok) { T.$("lb-status").textContent = b.error || ""; return; }
    T.$("lb-status").innerHTML = boardBadge(b.status);
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
}
