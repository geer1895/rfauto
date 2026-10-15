/* rfauto Run 历史页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   指标筛选 + 可排序表 + 骨架屏/空态。 */

import { S, T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal）
import { apiFetch, viewSignal } from "./api.js";
import { esc, help } from "./dom.js";
import { bindClickRows, kitApplyClickRowAttrs, kitEmptyState, kitSkeletonRows } from "./kit.js";
import { openRun } from "./router.js";
import { makeSortable } from "./sortable.js";

/* ═══ Run 历史（指标筛选）═══ */
export async function pageRuns() {
  const v = T.$("view-runs");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>每一行 = 一次仿真（run）。点击行进入详情：S 参数曲线（可切分量）、3D 模型、产物、配方快照。</li>
      <li>顶部筛选：按 run_id 文本、通道、S11 阈值过滤（如只看 -20dB 以下的）。</li>`) +
    `<h2 class='page'>Run 历史</h2>
      <div class='panel'><div class='toolbar'>
        <input id='f-text' size='18' placeholder='run_id 过滤…'>
        <select id='f-adapter'><option value=''>全部通道</option><option>fake</option><option>openems</option><option>hfss</option></select>
        S11 优于: <input id='f-s11' size='8' placeholder='-20'> dB
        <button class='minor' id='f-clear'>清除</button>
        <span id='f-count' class='muted'></span>
      </div>
      <table id='runs-table' data-sortable><thead>
        <tr><th scope="col">run_id</th><th scope="col">时间</th><th scope="col">adapter</th><th scope="col">带内 S11</th><th scope="col">状态</th><th scope="col">best 指标</th></tr>
      </thead><tbody></tbody></table></div>`;
  // A8-A（R6 审计 P-2）：首拉骨架屏——表体占位行（shimmer 条，reduced-motion
  // 降级静态灰块）；/api/runs 数据到达后 render() 整体替换。
  const skTable = T.$("runs-table");
  if (skTable && skTable.tBodies[0])
    skTable.tBodies[0].innerHTML = kitSkeletonRows(5, 6);
  const data = await apiFetch("/api/runs", { signal: viewSignal("runs") });
  if (data.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  S.allRuns = data.runs || [];
  const render = () => {
    const ft = T.$("f-text").value.trim().toLowerCase();
    const fa = T.$("f-adapter").value;
    const fs = parseFloat(T.$("f-s11").value);
    const rows = S.allRuns.filter((r) => {
      if (ft && !(r.run_id || "").toLowerCase().includes(ft)) return false;
      if (fa && r.adapter !== fa) return false;
      const m11 = r.metrics?.s11_db_max_in_band;
      if (!isNaN(fs) && !(typeof m11 === "number" && m11 <= fs)) return false;
      return true;
    });
    T.$("f-count").textContent = `${rows.length} / ${S.allRuns.length}`;
    const tb = T.$("runs-table").tBodies[0];
    tb.innerHTML = "";
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      const metrics = r.metrics
        ? Object.entries(r.metrics).map(([k, v2]) => `${esc(k)}=${typeof v2 === "number" ? v2.toFixed(3) : esc(v2)}`).join(" ")
        : "";
      const m11 = r.metrics?.s11_db_max_in_band;
      tr.innerHTML = `<td>${esc(r.run_id || "")}</td><td>${esc(r.timestamp || r.ts || "")}</td><td>${esc(r.adapter || "")}</td><td>${esc(typeof m11 === "number" ? m11.toFixed(2) + " dB" : "-")}</td><td>${T.badge(r.status || "done", "muted")}</td><td class="muted">${metrics}</td>`;
      tr.dataset.id = r.run_id || ""; // UI-R4：激活回调按行取 id（bindClickRows 单入口）
      // UI-R4：键盘可达三件套（tr 行 role:null 保 row/cell 语义；
      // aria-label 行动作读屏可闻——run_id 经 setAttribute 字面量语境）
      kitApplyClickRowAttrs(tr, { role: null, label: "打开 run 详情：" + (r.run_id || "") });
      if (tr.children[0]) tr.children[0].title = r.run_id || ""; // W7-C：截断列悬停见全名
      tb.appendChild(tr);
    }
    // A4-C：单入口收编（hash 深链同步，R6 R-2）+ UI-R4：click/Enter/Space 同一激活
    bindClickRows(tb, (tr) => openRun(tr.dataset.id), "tr.clickable");
    if (!rows.length) {
      // A8-A（R6 审计 P-3）：筛选空态三件式（表体形态=colspan 行包 empty-state；
      // 动作钮转触既有「清除筛选」逻辑）
      tb.innerHTML = `<tr><td colspan="6">` + kitEmptyState("无匹配 run——调整筛选条件试试",
        { icon: "☰", label: "清除筛选", id: "runs-empty-clear" }) + `</td></tr>`;
      const rc = T.$("runs-empty-clear");
      const fc = T.$("f-clear");
      if (rc && fc) rc.onclick = () => fc.click();
    }
    // aurora36 W3-B（P1-7）：筛选重渲染后重放当前排序（makeSortable 幂等）
    const sruns = makeSortable(T.$("runs-table"));
    if (sruns) sruns.refresh();
  };
  ["f-text", "f-adapter", "f-s11"].forEach((id) => {
    T.$(id).oninput = render;
    T.$(id).onchange = render;
  });
  T.$("f-clear").onclick = () => {
    T.$("f-text").value = ""; T.$("f-adapter").value = ""; T.$("f-s11").value = "";
    render();
  };
  render();
}
