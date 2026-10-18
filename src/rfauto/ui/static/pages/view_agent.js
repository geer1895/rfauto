/* rfauto Agent 助手页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   模型设置 + 审批收件箱 + 沙箱草稿 + 浮动可拖拽对话卡片。 */

import { S, T } from "./context.js";
import { esc, escAttr, help, renderMarkdown } from "./dom.js";
import { kitPanelHead, kitTable } from "./kit.js";

let _agentReload = null; // R-1：refresh 局部刷新转发登记（agentCtx 消费，pageAgent 内赋值）

/* ═══ Agent 助手（设置 + 收件箱 diff + 浮动可拖拽对话卡片）═══ */
export async function pageAgent() {
  const v = T.$("view-agent");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>⚙ 模型设置</b>：填 OpenAI 兼容 API（base_url/model/api_key，如 deepseek、gpt、本地 ollama）并保存后，对话即切换为真实 LLM——它能调用框架工具（查 run、诊断、校验配方、生成参数提案）。</li>
      <li>未配置时为<b>指令模式</b>：直接发 "list runs"、"validate recipes/xxx.yaml"、"diagnose run_id" 等指令。</li>
      <li><b>安全边界</b>：agent 的工具大多是只读的；唯一会写盘的是「参数提案」——只写 recipes/ 下的提案文件，且必须走三层 Gate + 你在收件箱批准（diff 形式展示改了什么）才生效。<b>它接触不到框架源码</b>。</li>
      <li>内置系统提示词见下方「内置提示词」折叠块（完全透明）。</li>`) +
    `<h2 class='page'>Agent 助手</h2>
      <div class='panel'><div class='toolbar'>
        <b>⚙ 模型设置</b>
        base_url: <input id='chat-url' size='28' placeholder='https://api.xxx.com/v1'>
        model: <input id='chat-model' size='16' placeholder='模型名'>
        api_key: <input id='chat-key' size='18' type='password' placeholder='不改则留空'>
        <button class='act' id='chat-save'>保存</button>
        <button class='minor' id='chat-clear'>清空对话</button>
        <span id='chat-cfg-badge'></span>
      </div>
      <details class='help' style='margin:0'><summary>内置提示词（系统 prompt，透明可查）</summary>
        <pre id='chat-prompt' style='max-height:200px'></pre></details></div>
      ${kitPanelHead("审批收件箱（提案以参数 diff 展示）")}<div id='inbox-list' class='muted'>加载中...</div></div>
      ${kitPanelHead("Agent 沙箱草稿（agent 自主编辑先落沙箱；送审批走三层 Gate 进收件箱）")}
        <div id='sandbox-list' class='muted'>加载中...</div></div>
      <div class='panel'><button class='act' id='chat-open'>💬 打开对话浮窗</button>
        <span class="muted">浮窗可拖拽（按住标题栏）、右下角缩放、可最小化，位置自动记忆。</span></div>`;
  T.$("chat-open").onclick = () => openChatFloat(true);
  T.$("chat-clear").onclick = async () => {
    await T.api("/api/chat/reset", { method: "POST" });
    const log = document.getElementById("chat-log");
    if (log) log.innerHTML = "";
    S.chatLog = [];
    localStorage.removeItem("rfauto-chat");
  };
  T.$("chat-save").onclick = async () => {
    const r = await T.api("/api/chat/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: T.$("chat-url").value.trim(),
                             model: T.$("chat-model").value.trim(),
                             api_key: T.$("chat-key").value }),
    });
    T.msg(r.ok ? "模型设置已保存" : "保存失败", !!r.ok);
    loadCfgBadge();
  };
  loadCfgBadge();
  const pr = await T.api("/api/chat/prompt");
  T.$("chat-prompt").textContent = pr.prompt || "(未取到)";
  await loadInbox();
  await loadSandbox();
  S.chatLog = JSON.parse(localStorage.getItem("rfauto-chat") || "[]");
  openChatFloat(false);
  for (const m of S.chatLog) appendBubble(m.who, m.text, m.tools);
  await updateStats();
  // 快捷提问 chips（点选即发送）
  const QUICK = ["分析最近一次 run", "list solvers", "校验 recipes/wilkinson_pd_v1.yaml",
                 "帮 wilkinson 配方提议一组新参数"];
  const q = document.getElementById("chat-suggest");
  if (q) {
    q.style.display = "flex";
    for (const t of QUICK) {
      const b = document.createElement("button");
      b.className = "chipbtn";
      b.textContent = t;
      b.onclick = () => { T.$("chat-in").value = t; sendChat(); };
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
      el.insertAdjacentHTML("beforeend",
        `<div class="muted" style="font-size:var(--text-xs);margin-top:var(--space-1)">🔧 工具: ${esc([...new Set(tools)].join(" → "))}</div>`);
    }
    log.scrollTop = log.scrollHeight;
  }
  async function updateStats() {
    let stats;
    try { stats = (await T.api("/api/chat/stats")).stats; }
    catch { return; }
    const bar = document.getElementById("chat-stats");
    if (!bar) return;
    const fmt = (s2) => s2 >= 60 ? `${Math.floor(s2 / 60)}m${Math.round(s2 % 60)}s` : `${s2.toFixed(1)}s`;
    const hit = stats.prompt_tokens
      ? ` · 缓存命中 ${Math.round(stats.cached_tokens / stats.prompt_tokens * 100)}%` : "";
    bar.textContent = `轮数 ${stats.turns} · LLM ${fmt(stats.llm_elapsed_s)}（${stats.llm_calls} 次调用）`
      + ` · 工具 ${stats.tool_calls} 次耗时 ${fmt(stats.tool_elapsed_s)}`
      + ` · 输入 ${stats.prompt_tokens} tok · 输出 ${stats.completion_tokens} tok${hit}`;
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
    win.setAttribute("aria-label", "Agent 对话浮窗");
    win.style.cssText = `position:fixed;z-index:var(--z-fixed);display:flex;flex-direction:column;
      background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-md);
      box-shadow:var(--shadow);overflow:hidden`;
    win.innerHTML = `
      <div id="cf-head" style="display:flex;align-items:center;gap:var(--space-2);padding:var(--space-2) var(--space-3);
           background:var(--panel2);cursor:move;user-select:none">
        <b style="flex:1;font-size:var(--text-sm);color:var(--accent)">💬 对话（历史自动保存）</b>
        <button class="minor" id="cf-min" style="padding:1px 8px">—</button>
        <button class="minor" id="cf-close" style="padding:1px 8px">×</button>
      </div>
      <div id="chat-log" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:var(--space-2);padding:10px"></div>
      <div id="chat-suggest" class="toolbar" style="margin:0;padding:0 10px"></div>
      <div class="toolbar" style="margin:0;padding:6px 10px">
        <input id='chat-in' style='flex:1' placeholder='例如：分析最近一次 run 并提议参数修改'>
        <button class='act' id='chat-send'>发送</button>
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
    for (const m of S.chatLog) appendBubble(m.who, m.text, m.tools);
  }

  async function loadCfgBadge() {
    const cfg = await T.api("/api/chat/settings");
    T.$("chat-url").value = cfg.base_url || "";
    T.$("chat-model").value = cfg.model || "";
    T.$("chat-cfg-badge").innerHTML = cfg.configured
      ? T.badge("已配置真实 LLM", "ok") : T.badge("未配置（指令模式）", "muted");
  }

  /* 提案 → 参数 diff 表（当前配方值 vs 提案值） */
  async function renderProposal(p) {
    const div = document.createElement("div");
    div.className = "panel";
    div.style.marginBottom = "10px";
    const recipePath = p.recipe || "";
    let rows = "";
    try {
      const cur = await T.api("/api/recipe?path=" + encodeURIComponent(recipePath));
      const base = {};
      for (const x of cur.params || []) base[x.name] = x.value;
      const params = p.params || {};
      rows = Object.entries(params).map(([n, nv]) => {
        const old = base[n];
        const changed = old !== undefined && old !== nv;
        const pct = (typeof old === "number" && typeof nv === "number" && old)
          ? ` (${nv > old ? "+" : ""}${((nv - old) / old * 100).toFixed(1)}%)` : "";
        const cls = changed ? "color:var(--warn)" : "";
        return `<tr><td><b>${esc(n)}</b></td><td class="muted">${esc(old ?? "(新增)")}</td>
          <td style="${cls}">${esc(nv)}${pct}</td></tr>`;
      }).join("");
    } catch {
      rows = `<tr><td colspan="3" class="muted">当前配方值不可读，仅列提案值</td></tr>` +
        Object.entries(p.params || {}).map(([n, nv]) => `<tr><td><b>${esc(n)}</b></td><td>-</td><td>${esc(nv)}</td></tr>`).join("");
    }
    div.innerHTML = `<b>${escAttr(recipePath)}</b> ${T.badge("参数提案", "warn")}
      ${kitTable({ columns: ["参数", "当前值", "提案值"], rowsHtml: rows, empty: "" })}
      <div class="toolbar" style="margin-top:var(--space-2)"><button class='act'>批准并执行</button>
      <span class="muted">token: ${escAttr(p.token_hash || "")}</span></div>`;
    div.querySelector("button").onclick = async () => {
      // W7-C（加载态统一）：审批 POST 期间禁用防双击重复批准；失败恢复可重试
      const approveBtn = div.querySelector("button");
      approveBtn.disabled = true;
      const r = await T.api("/api/inbox/approve", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_hash: p.token_hash, recipe: recipePath, adapter: "fake" }),
      });
      if (!r.ok) approveBtn.disabled = false;
      T.msg(r.ok ? "已批准并执行" : "审批失败: " + (r.error || r.errors?.join("; ") || ""), !!r.ok);
      loadInbox();
    };
    return div;
  }

  async function loadInbox() {
    const d = await T.api("/api/inbox");
    const el = T.$("inbox-list");
    if (!(d.pending || []).length) { el.innerHTML = "<span class='muted'>无待审批提案</span>"; return; }
    el.innerHTML = "";
    for (const p of d.pending)
      el.appendChild(await renderProposal(p));
  }

  /* Agent 沙箱草稿：列表 + 参数差异 + unified diff + 送审批 */
  async function loadSandbox() {
    const el = T.$("sandbox-list");
    if (!el) return;
    const d = await T.api("/api/sandbox/drafts");
    if (!d.ok) { el.innerHTML = "<span class='muted'>沙箱状态不可读</span>"; return; }
    if (!(d.drafts || []).length) {
      el.innerHTML = "<span class='muted'>无沙箱草稿（agent 在对话中编辑配方后会出现在这里）</span>";
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
            `<tr><td><b>${esc(n)}</b></td><td class="muted">${esc(c.old ?? "(新增)")}</td><td style="color:var(--warn)">${esc(c.new ?? "(删除)")}</td></tr>`).join("")
        : `<tr><td colspan="3" class="muted">无参数差异${item.recipe ? "" : "（草稿未匹配到 recipes/ 源配方）"}</td></tr>`;
      div.innerHTML = `<b>${escAttr(item.draft.split(/[\\/]/).pop())}</b>
        ${item.recipe ? T.badge(item.recipe, "ok") : T.badge("来源未匹配", "muted")}
        <table><thead><tr><th scope="col">参数</th><th scope="col">当前值</th><th scope="col">草稿值</th></tr></thead><tbody>${rows}</tbody></table>
        <div class="toolbar" style="margin-top:var(--space-2)">
          ${item.recipe ? `<button class='minor' data-act='diff'>查看 diff</button>
          <button class='act' data-act='promote'>送审批（进收件箱）</button>` : ""}
          <span class="muted">promote 只放行 params 差异，其余节差异会被 Gate 拒绝</span></div>
        <pre data-role='diffbox' style='display:none;max-height:260px;overflow:auto'></pre>`;
      const diffBtn = div.querySelector("[data-act='diff']");
      if (diffBtn) diffBtn.onclick = async () => {
        const box = div.querySelector("[data-role='diffbox']");
        if (box.style.display === "none") {
          const r = await T.api("/api/sandbox/diff?recipe=" + encodeURIComponent(item.recipe));
          box.textContent = r.ok ? (r.unified_diff || "(无文本差异)") : (r.error || "diff 失败");
          box.style.display = "";
          diffBtn.textContent = "收起 diff";
        } else { box.style.display = "none"; diffBtn.textContent = "查看 diff"; }
      };
      const promoteBtn = div.querySelector("[data-act='promote']");
      if (promoteBtn) promoteBtn.onclick = async () => {
        promoteBtn.disabled = true;
        const r = await T.api("/api/sandbox/promote", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ recipe: item.recipe }),
        });
        if (r.ok) {
          T.msg("已生成提案，等你在收件箱批准", true);
          loadInbox();
        } else {
          T.msg("promote 被拒: " + (r.error || (r.errors || []).join("; ") || "未知原因"), false);
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
    if (!text || (btn && btn.disabled)) return; // W7-C：发送中防重入
    inp.value = "";
    appendBubble("user", text);
    S.chatLog.push({ who: "user", text });
    localStorage.setItem("rfauto-chat", JSON.stringify(S.chatLog.slice(-100)));
    log.insertAdjacentHTML("beforeend",
      `<div class='bubble bot'><span class='spin'></span> 思考中（可能连续调用多个工具，约 10-60 秒，复杂任务可能更久）…</div>`);
    log.scrollTop = log.scrollHeight;
    // W7-C（加载态统一）：fetch 期间发送钮 disabled+文案提示（与 tune/uq 既有
    // 口径同构）；api() 已全局兜错不抛，finally 恢复兜异常路径不卡死按钮
    if (btn) { btn.disabled = true; btn.textContent = "发送中…"; }
    let r;
    try {
      r = await T.api("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "发送"; }
    }
    const reply = r.reply || r.response || r.text || JSON.stringify(r);
    log.lastChild.remove();
    appendBubble("bot", reply, r.tools);
    S.chatLog.push({ who: "bot", text: reply, tools: r.tools });
    localStorage.setItem("rfauto-chat", JSON.stringify(S.chatLog.slice(-100)));
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
