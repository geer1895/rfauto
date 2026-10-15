/* rfauto 调度队列页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移，
   PR-9）：战役计划 + G13 决策日志 + remote 面只读组装。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { bindClickRows, bindEmptyStates, kitBadgeCls, kitClickRowAttrs, kitEmptyState, kitTable } from "./kit.js";
import { mountSortableTables } from "./sortable.js";

/* ═══ PR-9 调度队列页（ge8b Wave B 席B3）：战役队列 + G13 决策日志 ═══ */
export async function pageQueue() {
  const v = T.$("view-queue");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>战役队列=runs/ 下已落盘的 campaign.plan.json（确定性拆解的阶段计划）；
          <b>决策日志</b>出自 G13 确定性调度前置步（派发顺序/预测时长来源/拒绝清单的审计事件）。</li>
      <li><b>remote 面</b>（可选）：填机器名后按战役显示 HFSS 阶段的远端附着配置增量
          （只读组装，零真连）；mTLS 是条件项，按服务器接入说明口径如实登记。</li>
      <li>数据全部出自服务层既有函数，本页只渲染。</li>`) +
    `<h2 class='page'>调度队列 <small>战役计划 · G13 决策日志（PR-9）</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>runs 根</b><input id='q-root' value='runs' style='width:200px'>
         <b>remote 机器</b><input id='q-machine' placeholder='（留空=不查 remote 面）' style='width:220px'>
         <button class='minor' id='q-reload'>刷新</button>
         <span id='q-info' class='muted'></span></div>
       <div id='q-table' style='margin-top:var(--space-2)'></div>
     </div>
     <div id='q-detail' style='margin-top:var(--space-3)'></div>`;
  async function load() {
    const q = new URLSearchParams({ root: T.$("q-root").value || "runs" });
    const machine = T.$("q-machine").value.trim();
    if (machine) q.set("machine", machine);
    const d = await T.api("/api/campaign_queue?" + q);
    const el = T.$("q-table");
    // A8-A 注：本点错误提示保持 ✗ 形态不迁 kitErrorPanel——跨席 ✗ 计数钉
    // （test_ui_lifecycle/test_ui_tools_page 双钉 ==6）如实不清偿；错误态
    // 动作化落 datasets/anchors 两点（本注释故不写钉串字面，防自增计数）。
    if (!d.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((d.errors || []).join("; "))}</span>`; return; }
    T.$("q-info").textContent = `${d.n_campaigns} 个战役计划${machine ? " · remote=" + machine : ""}`;
    if (!d.n_campaigns) {
      // A8-A（R6 审计 P-3）：空态三件式——引导去战役仪表盘立战役
      el.innerHTML = kitEmptyState("runs/ 下暂无 campaign.plan.json（先立战役）",
        { icon: "≣", label: "去战役仪表盘", view: "campaign" });
      bindEmptyStates(el);
      T.$("q-detail").innerHTML = "";
      return;
    }
    el.innerHTML = `<table data-sortable><thead><tr><th scope="col">战役</th><th scope="col">model</th><th scope="col">verdict</th>
      <th scope="col">阶段进度</th><th scope="col">调度</th><th scope="col">决策日志</th>${machine ? "<th scope='col'>remote</th>" : ""}</tr></thead><tbody>` +
      d.campaigns.map((c) => {
        const done = (c.stages || []).filter((s) => s.status === "done").length;
        const dead = (c.stages || []).filter((s) => s.status === "failed" || s.status === "aborted").length;
        const dl = c.scheduling ? (c.scheduling.decision_log || []) : [];
        const name = String(c.path || "").replace(/\\/g, "/").split("/").slice(-2, -1)[0] || c.path;
        const remote = c.remote
          ? (c.remote.ok
            ? (c.remote.remote_machine
              ? `<span style='color:var(--ok)'>✓ ${esc(c.remote.remote_machine.remote_machine || c.remote.machine)}</span>`
              : "<span class='muted'>无配置（本地零变化）</span>")
            : `<span style='color:var(--warn)'>✗ ${esc((c.remote.errors || []).join("; "))}</span>`)
          : "";
        return `<tr><td title='${escAttr(c.path)}'>${esc(name)}</td><td>${esc(c.model || "?")}</td>
          <td>${T.badge(c.verdict || "—", kitBadgeCls(c.verdict))}</td>
          <td>${done}/${c.n_stages}${dead ? ` <span style='color:var(--err)'>(死 ${dead})</span>` : ""}</td>
          <td>${c.scheduling && c.scheduling.ok ? `<span style='color:var(--ok)'>✓ ${esc(String(c.scheduling.n_jobs))} 作业</span>` : "<span class='muted'>—</span>"}</td>
          <td><a href='#' data-go='${escAttr(c.path)}' class='q-open' ${kitClickRowAttrs({ label: "查看决策日志（" + dl.length + " 条）" })}>${dl.length} 条</a></td>
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
    // aurora36 W3-B（P1-7）：战役表可排序——<table> 随 load() innerHTML 重建，
    // 每次渲染后重扫挂载（makeSortable 幂等；行内 .q-open 锚事件随节点重排不丢）
    mountSortableTables(el);
  }
  function renderDetail(c) {
    const dl = (c.scheduling && c.scheduling.decision_log) || [];
    const stages = c.stages || [];
    T.$("q-detail").innerHTML = `<div class='panel'>
      <b class='title'>${esc(c.model || c.path)} — 阶段与决策日志</b>
      <div style='margin:6px 0'>${stages.map((s) =>
        `${T.badge(s.stage + ":" + s.status, s.status === "done" ? "ok" : (s.status === "pending" ? "muted" : "err"))}${s.license_gated ? " <span class='muted'>(license)</span>" : ""}`).join(" ")}</div>
      ${dl.length
        ? kitTable({ // A7-A ui-kit 试点：表壳单源（kitTable；dl 非空分支才进，empty:"" 保空 tbody 等价）
            columns: ["#", "决策"], rows: dl, empty: "",
            rowHtml: (e, i) => {
              const line = typeof e === "string" ? e : JSON.stringify(e);
              return `<tr><td>${i + 1}</td><td>${esc(line)}</td></tr>`;
            },
          })
        : "<span class='muted'>该战役无决策日志（调度前置步未产出或旧计划）</span>"}
      ${c.remote ? `<div class='muted' style='margin-top:6px'>mTLS 状态：${esc(c.remote.mtls || "")}</div>` : ""}
    </div>`;
    T.$("q-detail").scrollIntoView({ block: "nearest" });
  }
  T.$("q-reload").onclick = load;
  T.$("q-machine").onchange = load;
  await load();
}
