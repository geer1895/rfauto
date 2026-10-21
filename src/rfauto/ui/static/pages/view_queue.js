/* rfauto 调度队列页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移，
   PR-9）：战役计划 + G13 决策日志 + remote 面只读组装。
   i18n（发布前软编码批 S2 残量清零）：help 块/详情面板/状态段全迁词表
   （queue.* 键域，zh 与旧字面逐字节同、en 新增）；表头 model/verdict/
   remote 为协议标识符刻意保留英文原文（豁免登记）；战役名/决策日志条目
   为 API 数据照旧 esc——数据非文案不迁。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// i18n（架构批 W1-S2 试点页 3）：壳标签 data-i18n+首扫；表头/空态随 load()
// 重建，文案一律 t() 渲染期烘焙（i18n.js 头注纪律）。
import { t, applyI18nRoot } from "./i18n.js";
import { bindClickRows, bindEmptyStates, kitBadgeCls, kitClickRowAttrs, kitEmptyState, kitTable } from "./kit.js";
import { mountSortableTables } from "./sortable.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 1 点）——
// 数据面全页（队列清单 load()，刷新钮与 ctx.refresh 共用）接
// viewSignal("queue") 切页收束 + aborted 短路（在途拉取不再写隐藏区）。
// 信封消费形态逐键不变（✗ 形态错误行=跨席计数钉保留）。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ PR-9 调度队列页（ge8b Wave B 席B3）：战役队列 + G13 决策日志 ═══ */
export async function pageQueue() {
  const v = T.$("view-queue");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("queue.help_1_lead")}<b>${t("queue.help_1_core")}</b>${t("queue.help_1_tail")}</li>
      <li><b>${t("queue.help_2_core")}</b>${t("queue.help_2_tail")}</li>
      <li>${t("queue.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='queue.title'>${t("queue.title")}</span> <small data-i18n='queue.subtitle'>${t("queue.subtitle")}</small></h2>
     <div class='panel'>
       <div class='toolbar'><b data-i18n='queue.runs_root'>${t("queue.runs_root")}</b><input id='q-root' value='runs' style='width:200px'>
         <b data-i18n='queue.machine_label'>${t("queue.machine_label")}</b><input id='q-machine' placeholder='${t("queue.machine_placeholder")}' style='width:220px' data-i18n-ph='queue.machine_placeholder'>
         <button class='minor' id='q-reload' data-i18n='queue.reload'>${t("queue.reload")}</button>
         <span id='q-info' class='muted'></span></div>
       <div id='q-table' style='margin-top:var(--space-2)'></div>
     </div>
     <div id='q-detail' style='margin-top:var(--space-3)'></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W1-S2）
  async function load() {
    const q = new URLSearchParams({ root: T.$("q-root").value || "runs" });
    const machine = T.$("q-machine").value.trim();
    if (machine) q.set("machine", machine);
    const d = await apiFetch("/api/campaign_queue?" + q,
      { signal: viewSignal("queue") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const el = T.$("q-table");
    // A8-A 注：本点错误提示保持 ✗ 形态不迁 kitErrorPanel——跨席 ✗ 计数钉
    // （test_ui_lifecycle/test_ui_tools_page 双钉 ==6）如实不清偿；错误态
    // 动作化落 datasets/anchors 两点（本注释故不写钉串字面，防自增计数）。
    if (!d.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((d.errors || []).join("; "))}</span>`; return; }
    T.$("q-info").textContent = t("queue.info_tpl", { n: d.n_campaigns }) +
      (machine ? " · remote=" + machine : "");
    if (!d.n_campaigns) {
      // A8-A（R6 审计 P-3）：空态三件式——引导去战役仪表盘立战役
      el.innerHTML = kitEmptyState(t("queue.empty"),
        { icon: "≣", label: t("queue.empty_action"), view: "campaign" });
      bindEmptyStates(el);
      T.$("q-detail").innerHTML = "";
      return;
    }
    el.innerHTML = `<table data-sortable><thead><tr><th scope="col">${t("queue.th_campaign")}</th><th scope="col">model</th><th scope="col">verdict</th>
      <th scope="col">${t("queue.th_stages")}</th><th scope="col">${t("queue.th_schedule")}</th><th scope="col">${t("queue.th_decision_log")}</th>${machine ? "<th scope='col'>remote</th>" : ""}</tr></thead><tbody>` +
      d.campaigns.map((c) => {
        const done = (c.stages || []).filter((s) => s.status === "done").length;
        const dead = (c.stages || []).filter((s) => s.status === "failed" || s.status === "aborted").length;
        const dl = c.scheduling ? (c.scheduling.decision_log || []) : [];
        const name = String(c.path || "").replace(/\\/g, "/").split("/").slice(-2, -1)[0] || c.path;
        const remote = c.remote
          ? (c.remote.ok
            ? (c.remote.remote_machine
              ? `<span style='color:var(--ok)'>✓ ${esc(c.remote.remote_machine.remote_machine || c.remote.machine)}</span>`
              : "<span class='muted'>" + t("queue.remote_no_config") + "</span>")
            : `<span style='color:var(--warn)'>✗ ${esc((c.remote.errors || []).join("; "))}</span>`)
          : "";
        return `<tr><td title='${escAttr(c.path)}'>${esc(name)}</td><td>${esc(c.model || "?")}</td>
          <td>${T.badge(c.verdict || "—", kitBadgeCls(c.verdict))}</td>
          <td>${done}/${c.n_stages}${dead ? ` <span style='color:var(--err)'>${t("queue.dead_tpl", { n: dead })}</span>` : ""}</td>
          <td>${c.scheduling && c.scheduling.ok ? `<span style='color:var(--ok)'>✓ ${t("queue.jobs_tpl", { n: esc(String(c.scheduling.n_jobs)) })}</span>` : "<span class='muted'>—</span>"}</td>
          <td><a href='#' data-go='${escAttr(c.path)}' class='q-open' ${kitClickRowAttrs({ label: t("queue.open_log_aria_tpl", { n: dl.length }) })}>${t("queue.entries_tpl", { n: dl.length })}</a></td>
          ${machine ? `<td>${remote}</td>` : ""}</tr>`;
      }).join("") + "</tbody></table>";
    T.$("q-detail").innerHTML = "";
    // UI-R4：决策日志锚键盘可达收编 bindClickRows——role=button+tabindex
    // （kit 属性串）；click/Enter/Space 全 preventDefault，href='#' 页顶
    // 跳动面（A6 P1-5 指控点）随之闭合。视觉零变化（a 无 href 专属样式）。
    bindClickRows(el, (a) => {
      const c = d.campaigns.find((x) => x.path === a.dataset.go);
      if (c) renderDetail(c);
    }, ".q-open");
    // 架构批 W3-B（P1-7）：战役表可排序——<table> 随 load() innerHTML 重建，
    // 每次渲染后重扫挂载（makeSortable 幂等；行内 .q-open 锚事件随节点重排不丢）
    mountSortableTables(el);
  }
  function renderDetail(c) {
    const dl = (c.scheduling && c.scheduling.decision_log) || [];
    const stages = c.stages || [];
    T.$("q-detail").innerHTML = `<div class='panel'>
      <b class='title'>${esc(c.model || c.path)}${t("queue.detail_title_suffix")}</b>
      <div style='margin:6px 0'>${stages.map((s) =>
        `${T.badge(s.stage + ":" + s.status, s.status === "done" ? "ok" : (s.status === "pending" ? "muted" : "err"))}${s.license_gated ? " <span class='muted'>(license)</span>" : ""}`).join(" ")}</div>
      ${dl.length
        ? kitTable({ // A7-A ui-kit 试点：表壳单源（kitTable；dl 非空分支才进，empty:"" 保空 tbody 等价）
            columns: ["#", t("queue.th_decision")], rows: dl, empty: "",
            rowHtml: (e, i) => {
              const line = typeof e === "string" ? e : JSON.stringify(e);
              return `<tr><td>${i + 1}</td><td>${esc(line)}</td></tr>`;
            },
          })
        : "<span class='muted'>" + t("queue.no_decision_log") + "</span>"}
      ${c.remote ? `<div class='muted' style='margin-top:6px'>${t("queue.mtls_status_lead")}${esc(c.remote.mtls || "")}</div>` : ""}
    </div>`;
    T.$("q-detail").scrollIntoView({ block: "nearest" });
  }
  T.$("q-reload").onclick = load;
  T.$("q-machine").onchange = load;
  await load();
}

/* ═══ R-1（架构批 W3-S12）：PageContext 增量钩子 queueCtx ═════════════
   refresh=表数据重拉（runs 同模板——pageQueue 幂等：壳判 innerHTML 已在即
   跳过，campaign_queue 按当前 runs 根/机器输入重拉；决策日志详情随表整清）。
   无轮询面，leave 不需要。 */
export const queueCtx = {
  refresh: () => pageQueue(),
};
