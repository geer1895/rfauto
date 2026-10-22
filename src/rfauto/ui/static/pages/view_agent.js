/* rfauto Agent 助手页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   模型设置 + 审批收件箱 + 沙箱草稿 + 浮动可拖拽对话卡片。
   i18n（aurora_h W4-S1 半程收尾全清）：help 块分段 t()（dashboard 先例）、
   统计条/审批面板/沙箱面板文案全迁词表（agent.* 键域，zh 与旧字面逐字节
   同、en 新增）——拼接数据段（run id/参数名/diff 值）照旧视图侧 esc 后拼
   模板，词表值零 HTML；toast/announce 走 textContent 单点。 */

import { T } from "./context.js";
import { esc, escAttr, help, renderMarkdown } from "./dom.js";
import { kitConfirm, kitPanelHead, kitTable } from "./kit.js";
// i18n（aurora_f W6-S21 扩面页 5；W8-S32 批 3 补对话浮窗静态面）：壳静态
// 标签 data-i18n(-ph)+首扫；徽章/空态/浮窗标题/输入占位/发送态/思考态/
// 工具前缀/快捷提问随渲染分支重建，文案 t() 渲染期烘焙（对话气泡正文与
// LLM 回复=模型输出走 marked+净化链，不进词表；统计条与审批/沙箱面板=
// 后续波次）。
import { t, applyI18nRoot } from "./i18n.js";
// P8-9（aurora_f W3-S9，R1 §面4）：T.api→apiFetch 统一请求层（本页 12 点）——
// 数据面板拉取（设置徽章/收件箱/沙箱/提示词/统计）接 viewSignal("agent")
// 切页收束 + aborted 短路（agentCtx.refresh 与进页拉取不再写隐藏区）；
// 用户动作 POST（发对话/重置/保存设置/审批/promote/diff）保持无 signal
// ——对话浮窗挂在 document.body 跨页存活，发送中的对话请求不因切页取消。
import { apiFetch, viewSignal } from "./api.js";

let _agentReload = null; // R-1：refresh 局部刷新转发登记（agentCtx 消费，pageAgent 内赋值）

/* 对话历史（W6-S2 S 状态收编，R2 审计 §面2：原 S.chatLog 单模块私有键
   降级模块级——属主=本模块，契约表见 context.js；localStorage rfauto-chat
   slice(-100) 持久语义不变）。 */
let _chatLog = [];

/* ═══ 人性化三批（2026-10-19 审计 ✗4）：指令模式 JSON 全量转储→结构化摘要 ═══
   病灶：指令模式（LLM 未配置/调用失败回退）的 list solvers/validate/
   diagnose/propose 回复正文=服务端 json.dumps 全量原文（数百行裸 JSON 直接
   面客）。修法=呈现层识别"正文是 JSON 转储"→ 改渲染摘要气泡（徽章+白话
   统计+折叠详情 <pre>，首次展开才序列化——detail 失败诊断包同款纪律）；
   自然语言正文（list runs 一句话/LLM markdown 回复）恒不命中零扰动。
   两函数纯串构建/纯解析零 DOM（node 行为钉可测，test_ui_modules_behavior
   同笔钉）。 */
/* JSON 转储识别：剥可选回退前缀行（[LLM 调用失败…]——只认 [LLM 开头，
   不吃 JSON 数组本体）后整体 parse 为对象/数组才算。 */
export function parseChatJsonDump(text) {
  let body = String(text == null ? "" : text);
  const m = body.match(/^\s*\[LLM[^\]]*\]\s*/);
  if (m) body = body.slice(m[0].length);
  if (!/^[{[]/.test(body)) return null;
  try {
    const v = JSON.parse(body);
    return v && typeof v === "object" ? v : null;
  } catch { return null; }
}

/* 摘要行构建（信封常见键 best-effort：solvers/runs 数组报数+可用数、
   total、ok 旗+错误原文；未知形态兜底取前 3 个可读字段——标量直出、
   数组报数，不递归展开）。动态数据一律 esc 单点转义（插值只收已构串
   局部变量，XSS 反向扫描口径零新增）。 */
export function chatCmdSummaryHtml(dump) {
  const d = (dump && typeof dump === "object") ? dump : {};
  const bits = [];
  if (Array.isArray(d.solvers)) {
    const n = d.solvers.length;
    bits.push(t("agent.cmd_solvers_tpl", { n }));
    let okN = 0;
    for (const s of d.solvers) if (s && s.available) okN++;
    bits.push(t("agent.cmd_available_tpl", { n: okN }));
  } else if (Array.isArray(d.runs)) {
    const n = d.runs.length;
    bits.push(t("agent.cmd_runs_tpl", { n }));
  } else if (typeof d.total === "number") {
    const n = d.total;
    bits.push(t("agent.cmd_total_tpl", { n }));
  }
  if (d.ok === false) {
    const e = Array.isArray(d.errors) && d.errors.length ? d.errors.join("; ")
      : (d.error != null ? String(d.error) : "");
    bits.push(e ? esc(e) : t("agent.cmd_fail"));
  } else if (!bits.length) {
    // 未知形态兜底：前 3 个可读字段（标量直出、数组报数，不递归展开）
    let shown = 0;
    for (const [k, v] of Object.entries(d)) {
      if (shown >= 3) break;
      if (typeof v === "number" || typeof v === "boolean") {
        bits.push(esc(k) + "=" + esc(String(v))); shown++;
      } else if (typeof v === "string" && v.length <= 80) {
        bits.push(esc(k) + "=" + esc(v)); shown++;
      } else if (Array.isArray(v)) {
        const n = v.length;
        bits.push(esc(k) + " × " + n); shown++;
      }
    }
    if (!bits.length) bits.push(t("agent.cmd_ok"));
  }
  const summary = bits.join(" · ");
  return `<span class="badge ok">${esc(t("agent.cmd_badge"))}</span> ` +
    `<span class="muted">${summary}</span>`;
}

/* ═══ Agent 助手（设置 + 收件箱 diff + 浮动可拖拽对话卡片）═══ */
export async function pageAgent() {
  const v = T.$("view-agent");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>${t("agent.model_settings")}</b>${t("agent.help_1_tail")}</li>
      <li>${t("agent.help_2_lead")}<b>${t("agent.help_2_core")}</b>${t("agent.help_2_tail")}</li>
      <li><b>${t("agent.help_3_core")}</b>${t("agent.help_3_mid")}<b>${t("agent.help_3_core2")}</b>${t("agent.help_3_tail")}</li>
      <li>${t("agent.help_4")}</li>`) +
    `<h2 class='page' data-i18n='agent.title'>${t("agent.title")}</h2>
      <div class='panel'><div class='toolbar'>
        <b data-i18n='agent.model_settings'>${t("agent.model_settings")}</b>
        base_url: <input id='chat-url' size='28' placeholder='https://api.xxx.com/v1'>
        model: <input id='chat-model' size='16' placeholder='${t("agent.ph_model")}' data-i18n-ph='agent.ph_model'>
        api_key: <input id='chat-key' size='18' type='password' placeholder='${t("agent.ph_key")}' data-i18n-ph='agent.ph_key'>
        <button class='act' id='chat-save' data-i18n='agent.save'>${t("agent.save")}</button>
        <button class='minor' id='chat-clear' data-i18n='agent.clear_chat'>${t("agent.clear_chat")}</button>
        <span id='chat-cfg-badge'></span>
      </div>
      <details class='help' style='margin:0'><summary data-i18n='agent.prompt_summary'>${t("agent.prompt_summary")}</summary>
        <pre id='chat-prompt' style='max-height:200px'></pre></details></div>
      ${kitPanelHead(t("agent.inbox_title"))}<div id='inbox-list' class='muted'>${t("agent.loading")}</div></div>
      ${kitPanelHead(t("agent.sandbox_title"))}
        <div id='sandbox-list' class='muted'>${t("agent.loading")}</div></div>
      <div class='panel'><button class='act' id='chat-open' data-i18n='agent.open_chat'>${t("agent.open_chat")}</button>
        <span class="muted" data-i18n='agent.float_hint'>${t("agent.float_hint")}</span></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W6-S21 扩面）
  T.$("chat-open").onclick = () => openChatFloat(true);
  // W6-S2（R1 P9-8）：清空对话=破坏性动作（POST reset+清 DOM+清本地记录，
  // 零撤销）——kitConfirm 确认闸（危险档，缺省焦点落取消钮）。
  T.$("chat-clear").onclick = () => kitConfirm({
    title: t("agent.clear_chat"),
    body: t("agent.clear_chat_body"),
    danger: true,
    onOk: async () => {
      await apiFetch("/api/chat/reset", { method: "POST" });
      const log = document.getElementById("chat-log");
      if (log) log.innerHTML = "";
      _chatLog = [];
      localStorage.removeItem("rfauto-chat");
      // 人性化三批（2026-10-19 审计 ⚠4）：清空后统计条同步复位——服务端
      // reset 已清零 turns/tokens，本地先清旧值再重读回填（fetch 失败=
      // 空条，不残留"轮数 1"假计数）。
      const bar = document.getElementById("chat-stats");
      if (bar) bar.textContent = "";
      updateStats();
    },
  });
  T.$("chat-save").onclick = async () => {
    const r = await apiFetch("/api/chat/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: T.$("chat-url").value.trim(),
                             model: T.$("chat-model").value.trim(),
                             api_key: T.$("chat-key").value }),
    });
    T.msg(r.ok ? t("agent.saved_ok") : t("agent.save_failed"), !!r.ok);
    loadCfgBadge();
  };
  loadCfgBadge();
  const pr = await apiFetch("/api/chat/prompt", { signal: viewSignal("agent") });
  // W8-S32 i18n 批 3：缺省提示 t() 烘焙
  if (!pr.aborted) T.$("chat-prompt").textContent = pr.prompt || t("agent.prompt_missing");
  await loadInbox();
  await loadSandbox();
  _chatLog = JSON.parse(localStorage.getItem("rfauto-chat") || "[]");
  openChatFloat(false);
  for (const m of _chatLog) appendHistoryEntry(m);
  await updateStats();
  // 快捷提问 chips（点选即发送）：文案迁词表（W8-S32 i18n 批 3），点击时
  // 按当前语言档烘焙为输入种子（循环变量 k 不遮蔽 i18n t——P3-7 同款纪律）
  const QUICK = ["agent.sug_analyze", "agent.sug_list", "agent.sug_validate",
                 "agent.sug_propose"];
  const q = document.getElementById("chat-suggest");
  if (q) {
    q.style.display = "flex";
    for (const k of QUICK) {
      const b = document.createElement("button");
      b.className = "chipbtn";
      b.textContent = t(k);
      b.onclick = () => { T.$("chat-in").value = t(k); sendChat(); };
      q.appendChild(b);
    }
  }

  function appendBubble(who, text, tools) {
    const log = document.getElementById("chat-log");
    if (!log) return;
    const md = who === "bot" && window.marked;
    log.insertAdjacentHTML("beforeend", `<div class='bubble ${who}${md ? " md" : ""}'></div>`);
    const el = log.lastChild;
    if (md) {
      // D-05：净化不可用时 renderMarkdown 内部降级 textContent（零注入）
      renderMarkdown(el,
        window.marked.parse(String(text), { breaks: true }));
    } else el.textContent = text;
    if (tools?.length) {
      // W8-S32 i18n 批 3：工具前缀 t() 烘焙（工具名清单=API 数据走 esc）
      el.insertAdjacentHTML("beforeend",
        `<div class="muted" style="font-size:var(--text-xs);margin-top:var(--space-1)">${t("agent.tools_prefix")}${esc([...new Set(tools)].join(" → "))}</div>`);
    }
    log.scrollTop = log.scrollHeight;
  }
  /* 摘要气泡（人性化三批，审计 ✗4）：摘要行 + 折叠详情（首次展开才序列化
     全量 JSON——detail 失败诊断包同款懒序列化纪律）。 */
  function appendCmdBubble(dump) {
    const log = document.getElementById("chat-log");
    if (!log) return;
    log.insertAdjacentHTML("beforeend",
      `<div class='bubble bot'>${chatCmdSummaryHtml(dump)}` +
      `<details style="margin-top:var(--space-2)"><summary class="muted" style="cursor:pointer;font-size:var(--text-xs)">${t("agent.cmd_details")}</summary>` +
      `<pre data-role='cmd-json' style="max-height:280px;overflow:auto;white-space:pre-wrap;user-select:all;font-size:var(--text-xs)"></pre></details></div>`);
    const el = log.lastChild;
    const pre = el.querySelector("[data-role='cmd-json']");
    el.querySelector("details").addEventListener("toggle", () => {
      if (pre && !pre.textContent) pre.textContent = JSON.stringify(dump, null, 2);
    });
    log.scrollTop = log.scrollHeight;
  }
  /* bot 回复分派：正文=JSON 全量转储→摘要气泡；自然语言→原 markdown 气泡。
     历史重放与实时回复同走本口（历史持久原文，重放渲染与首播一致）。 */
  function appendBotReply(text, tools) {
    const dump = parseChatJsonDump(text);
    if (dump) appendCmdBubble(dump);
    else appendBubble("bot", text, tools);
  }
  function appendHistoryEntry(m) {
    if (m.who === "bot") appendBotReply(m.text, m.tools);
    else appendBubble(m.who, m.text, m.tools);
  }
  async function updateStats() {
    // apiFetch 永不抛（失败折进 {ok:false} 信封）——旧 try/catch 已成死代码；
    // 失败/中止路径 .stats 为 undefined，直接消费 stats.prompt_tokens 会
    // TypeError 出 unhandled rejection（审查波 2 P3-3）——缺席守卫早退。
    const pr = await apiFetch("/api/chat/stats", { signal: viewSignal("agent") });
    if (pr.aborted || !pr.ok || !pr.stats) return; // UI-R12：切页取消/失败静默早退
    const stats = pr.stats;
    const bar = document.getElementById("chat-stats");
    if (!bar) return;
    const fmt = (s2) => s2 >= 60 ? `${Math.floor(s2 / 60)}m${Math.round(s2 % 60)}s` : `${s2.toFixed(1)}s`;
    const hit = stats.prompt_tokens
      ? t("agent.stats_cache_tpl", { p: Math.round(stats.cached_tokens / stats.prompt_tokens * 100) }) : "";
    // 统计条=textContent 单点（数字出自 /api/chat/stats，textContent 天然无插值面）
    bar.textContent = t("agent.stats_turns_tpl",
        { n: stats.turns, t: fmt(stats.llm_elapsed_s), c: stats.llm_calls })
      + t("agent.stats_tools_tpl", { n: stats.tool_calls, t: fmt(stats.tool_elapsed_s) })
      + t("agent.stats_tokens_tpl", { i: stats.prompt_tokens, o: stats.completion_tokens })
      + hit;
  }
  /* 浮动对话卡片：拖拽 + 缩放 + 最小化，几何记忆 */
  function openChatFloat(focus = true) {
    let win = document.getElementById("chat-float");
    if (win) { win.style.display = "flex"; if (focus) document.getElementById("chat-in")?.focus(); return; }
    const geo = Object.assign({ x: Math.max(0, window.innerWidth - 620), y: 90, w: 560, h: 560, min: false },
      JSON.parse(localStorage.getItem("rfauto-chat-geo") || "{}"));
    win = document.createElement("div");
    win.id = "chat-float";
    win.setAttribute("role", "dialog"); // PR-1 a11y：非模态浮窗也补 dialog 语义
    win.setAttribute("aria-label", t("agent.chat_float_aria")); // W8-S32 i18n 批 3
    win.style.cssText = `position:fixed;z-index:var(--z-fixed);display:flex;flex-direction:column;
      background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-md);
      box-shadow:var(--shadow);overflow:hidden`;
    win.innerHTML = `
      <div id="cf-head" style="display:flex;align-items:center;gap:var(--space-2);padding:var(--space-2) var(--space-3);
           background:var(--panel2);cursor:move;user-select:none">
        <b style="flex:1;font-size:var(--text-sm);color:var(--accent)">${t("agent.chat_title")}</b>
        <button class="minor" id="cf-min" style="padding:1px 8px">—</button>
        <button class="minor" id="cf-close" style="padding:1px 8px">×</button>
      </div>
      <div id="chat-log" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:var(--space-2);padding:10px"></div>
      <div id="chat-suggest" class="toolbar" style="margin:0;padding:0 10px"></div>
      <div class="toolbar" style="margin:0;padding:6px 10px">
        <input id='chat-in' style='flex:1' placeholder='${t("agent.chat_input_ph")}'>
        <button class='act' id='chat-send'>${t("agent.chat_send")}</button>
      </div>
      <div id="chat-stats" class="muted" style="font-size:var(--text-xs);padding:0 10px 6px"></div>
      <div id="cf-resize" style="position:absolute;right:0;bottom:0;width:16px;height:16px;
           cursor:nwse-resize;background:linear-gradient(135deg,transparent 50%,var(--accent) 50%)"></div>`;
    document.body.appendChild(win);
    const head = win.querySelector("#cf-head");
    const apply = () => {
      win.style.left = geo.x + "px"; win.style.top = geo.y + "px";
      win.style.width = geo.w + "px";
      win.style.height = geo.min ? "44px" : geo.h + "px";
      const body = win.querySelector("#chat-log");
      body.style.display = geo.min ? "none" : "";
      ["chat-suggest", "chat-stats"].forEach((id2) => {
        const e2 = win.querySelector("#" + id2);
        if (e2) e2.style.display = geo.min ? "none" : "";
      });
      const tb = win.querySelector(".toolbar");
      if (tb && tb !== head) tb.style.display = geo.min ? "none" : "";
    };
    apply();
    head.onpointerdown = (e) => {
      if (e.target.tagName === "BUTTON") return;
      const sx = e.clientX - geo.x, sy = e.clientY - geo.y;
      const mv = (ev) => {
        geo.x = Math.max(0, ev.clientX - sx); geo.y = Math.max(0, ev.clientY - sy);
        apply();
      };
      const up = () => { window.removeEventListener("pointermove", mv);
        window.removeEventListener("pointerup", up);
        localStorage.setItem("rfauto-chat-geo", JSON.stringify(geo)); };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
    };
    win.querySelector("#cf-resize").onpointerdown = (e) => {
      e.stopPropagation();
      const sw = geo.w, sh = geo.h, sx = e.clientX, sy = e.clientY;
      const mv = (ev) => {
        geo.w = Math.max(380, sw + ev.clientX - sx);
        geo.h = Math.max(260, sh + ev.clientY - sy);
        apply();
      };
      const up = () => { window.removeEventListener("pointermove", mv);
        window.removeEventListener("pointerup", up);
        localStorage.setItem("rfauto-chat-geo", JSON.stringify(geo)); };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
    };
    win.querySelector("#cf-min").onclick = () => { geo.min = !geo.min; apply();
      localStorage.setItem("rfauto-chat-geo", JSON.stringify(geo)); };
    win.querySelector("#cf-close").onclick = () => { win.style.display = "none"; };
    win.querySelector("#chat-send").onclick = sendChat;
    win.querySelector("#chat-in").onkeydown = (e) => { if (e.key === "Enter") sendChat(); };
    if (focus) document.getElementById("chat-in")?.focus();
    for (const m of _chatLog) appendHistoryEntry(m);
  }

  async function loadCfgBadge() {
    const cfg = await apiFetch("/api/chat/settings", { signal: viewSignal("agent") });
    if (cfg.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    T.$("chat-url").value = cfg.base_url || "";
    T.$("chat-model").value = cfg.model || "";
    T.$("chat-cfg-badge").innerHTML = cfg.configured
      ? T.badge(t("agent.cfg_ok"), "ok") : T.badge(t("agent.cfg_none"), "muted");
  }

  /* 提案 → 参数 diff 表（当前配方值 vs 提案值） */
  async function renderProposal(p) {
    const div = document.createElement("div");
    div.className = "panel";
    div.style.marginBottom = "10px";
    const recipePath = p.recipe || "";
    let rows = "";
    try {
      const cur = await apiFetch("/api/recipe?path=" + encodeURIComponent(recipePath),
        { signal: viewSignal("agent") });
      const base = {};
      for (const x of cur.params || []) base[x.name] = x.value;
      const params = p.params || {};
      rows = Object.entries(params).map(([n, nv]) => {
        const old = base[n];
        const changed = old !== undefined && old !== nv;
        const pct = (typeof old === "number" && typeof nv === "number" && old)
          ? ` (${nv > old ? "+" : ""}${((nv - old) / old * 100).toFixed(1)}%)` : "";
        const cls = changed ? "color:var(--warn)" : "";
        return `<tr><td><b>${esc(n)}</b></td><td class="muted">${esc(old ?? t("agent.diff_new"))}</td>
          <td style="${cls}">${esc(nv)}${pct}</td></tr>`;
      }).join("");
    } catch {
      rows = `<tr><td colspan="3" class="muted">${t("agent.proposal_unreadable")}</td></tr>` +
        Object.entries(p.params || {}).map(([n, nv]) => `<tr><td><b>${esc(n)}</b></td><td>-</td><td>${esc(nv)}</td></tr>`).join("");
    }
    div.innerHTML = `<b>${escAttr(recipePath)}</b> ${T.badge(t("agent.badge_proposal"), "warn")}
      ${kitTable({ columns: [t("agent.th_param"), t("agent.th_current"), t("agent.th_proposed")], rowsHtml: rows, empty: "" })}
      <div class="toolbar" style="margin-top:var(--space-2)"><button class='act'>${t("agent.approve_run")}</button>
      <span class="muted">token: ${escAttr(p.token_hash || "")}</span></div>`;
    div.querySelector("button").onclick = async () => {
      // W7-C（加载态统一）：审批 POST 期间禁用防双击重复批准；失败恢复可重试
      const approveBtn = div.querySelector("button");
      approveBtn.disabled = true;
      const r = await apiFetch("/api/inbox/approve", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_hash: p.token_hash, recipe: recipePath, adapter: "fake" }),
      });
      if (!r.ok) approveBtn.disabled = false;
      T.msg(r.ok ? t("agent.approved_ok")
                  : t("agent.approve_fail_lead") + (r.error || r.errors?.join("; ") || ""),
            !!r.ok);
      loadInbox();
    };
    return div;
  }

  async function loadInbox() {
    const d = await apiFetch("/api/inbox", { signal: viewSignal("agent") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const el = T.$("inbox-list");
    if (!(d.pending || []).length) { el.innerHTML = "<span class='muted'>" + t("agent.no_pending") + "</span>"; return; }
    el.innerHTML = "";
    for (const p of d.pending)
      el.appendChild(await renderProposal(p));
  }

  /* Agent 沙箱草稿：列表 + 参数差异 + unified diff + 送审批 */
  async function loadSandbox() {
    const el = T.$("sandbox-list");
    if (!el) return;
    const d = await apiFetch("/api/sandbox/drafts", { signal: viewSignal("agent") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    if (!d.ok) { el.innerHTML = "<span class='muted'>" + t("agent.sandbox_unreadable") + "</span>"; return; }
    if (!(d.drafts || []).length) {
      el.innerHTML = "<span class='muted'>" + t("agent.sandbox_empty") + "</span>";
      return;
    }
    el.innerHTML = "";
    for (const item of d.drafts) {
      const div = document.createElement("div");
      div.className = "panel";
      div.style.marginBottom = "10px";
      const changed = Object.entries(item.params_changed || {});
      const rows = changed.length
        ? changed.map(([n, c]) =>
            `<tr><td><b>${esc(n)}</b></td><td class="muted">${esc(c.old ?? t("agent.diff_new"))}</td><td style="color:var(--warn)">${esc(c.new ?? t("agent.diff_del"))}</td></tr>`).join("")
        : `<tr><td colspan="3" class="muted">${t("agent.no_param_diff")}${item.recipe ? "" : t("agent.draft_unmatched_suffix")}</td></tr>`;
      div.innerHTML = `<b>${escAttr(item.draft.split(/[\\/]/).pop())}</b>
        ${item.recipe ? T.badge(item.recipe, "ok") : T.badge(t("agent.source_unmatched"), "muted")}
        <table><thead><tr><th scope="col">${t("agent.th_param")}</th><th scope="col">${t("agent.th_current")}</th><th scope="col">${t("agent.th_draft")}</th></tr></thead><tbody>${rows}</tbody></table>
        <div class="toolbar" style="margin-top:var(--space-2)">
          ${item.recipe ? `<button class='minor' data-act='diff'>${t("agent.diff_view")}</button>
          <button class='act' data-act='promote'>${t("agent.promote_send")}</button>` : ""}
          <span class="muted">${t("agent.promote_note")}</span></div>
        <pre data-role='diffbox' style='display:none;max-height:260px;overflow:auto'></pre>`;
      const diffBtn = div.querySelector("[data-act='diff']");
      if (diffBtn) diffBtn.onclick = async () => {
        const box = div.querySelector("[data-role='diffbox']");
        if (box.style.display === "none") {
          const r = await apiFetch("/api/sandbox/diff?recipe=" + encodeURIComponent(item.recipe));
          box.textContent = r.ok ? (r.unified_diff || t("agent.diff_none")) : (r.error || t("agent.diff_fail"));
          box.style.display = "";
          diffBtn.textContent = t("agent.diff_hide");
        } else { box.style.display = "none"; diffBtn.textContent = t("agent.diff_view"); }
      };
      const promoteBtn = div.querySelector("[data-act='promote']");
      if (promoteBtn) promoteBtn.onclick = async () => {
        promoteBtn.disabled = true;
        const r = await apiFetch("/api/sandbox/promote", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ recipe: item.recipe }),
          timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：三层 Gate 分钟级
        });
        if (r.ok) {
          T.msg(t("agent.promoted_ok"), true);
          loadInbox();
        } else {
          T.msg(t("agent.promote_reject_lead") +
                (r.error || (r.errors || []).join("; ") || t("agent.reason_unknown")), false);
          promoteBtn.disabled = false;
        }
      };
      el.appendChild(div);
    }
  }

  async function sendChat() {
    const inp = document.getElementById("chat-in"), log = document.getElementById("chat-log");
    const btn = document.getElementById("chat-send");
    const text = inp.value.trim();
    // W7-C：发送中防重入（静默）；人性化三批（2026-10-19 审计 ⚠4）：空输入
    // 点发送不再无声——toast 提示后返回（两守卫拆分，防重入仍零反馈）。
    if (btn && btn.disabled) return;
    if (!text) { T.msg(t("agent.empty_input"), false); return; }
    inp.value = "";
    appendBubble("user", text);
    _chatLog.push({ who: "user", text });
    localStorage.setItem("rfauto-chat", JSON.stringify(_chatLog.slice(-100)));
    log.insertAdjacentHTML("beforeend",
      `<div class='bubble bot'><span class='spin'></span> ${t("agent.chat_thinking")}</div>`);
    log.scrollTop = log.scrollHeight;
    // W7-C（加载态统一）：fetch 期间发送钮 disabled+文案提示（与 tune/uq 既有
    // 口径同构）；api() 已全局兜错不抛，finally 恢复兜异常路径不卡死按钮。
    // W8-S32 i18n 批 3：发送/发送中文案 t() 烘焙
    if (btn) { btn.disabled = true; btn.textContent = t("agent.chat_sending"); }
    let r;
    try {
      r = await apiFetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
        timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：LLM 回复分钟级
      });
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = t("agent.chat_send"); }
    }
    const reply = r.reply || r.response || r.text || JSON.stringify(r);
    log.lastChild.remove();
    // 人性化三批（2026-10-19 审计 ✗4）：正文=JSON 全量转储（指令模式
    // list solvers/validate/diagnose/propose 的 json.dumps 产物）→ 摘要
    // 气泡（徽章+白话统计+折叠详情）；自然语言正文（list runs 一句话/
    // LLM markdown）照旧。历史持久原文，重放经 appendBotReply 同口渲染。
    appendBotReply(reply, r.tools);
    _chatLog.push({ who: "bot", text: reply, tools: r.tools });
    localStorage.setItem("rfauto-chat", JSON.stringify(_chatLog.slice(-100)));
    await updateStats();
    if (r.action && r.action !== "chat" && r.action !== "unknown") loadInbox();
  }

  /* R-1（aurora_e W4-S17）：refresh 局部刷新转发登记（agentCtx 消费）——
     数据面板（模型设置徽章/审批收件箱/沙箱草稿/用量统计）重拉；对话浮窗与
     气泡历史不动（appendBubble 非幂等，整页重跑会重复追加气泡）。内置提示词
     为静态系统 prompt（进页拉取一次即可），刷新不重拉。 */
  _agentReload = async () => {
    await loadCfgBadge();
    await loadInbox();
    await loadSandbox();
    await updateStats();
  };
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 agentCtx ═════════════
   refresh=数据面板重拉——闭包经模块级引用转发（sparams/campaign 同款模式）
   + 未进页 null 守卫。无轮询面，leave 不需要。 */
export const agentCtx = {
  refresh: async () => { const f = _agentReload; if (f) f(); },
};
