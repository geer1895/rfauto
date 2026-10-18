/* rfauto 求解器页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）。 */

import { T } from "./context.js";
import { esc, help } from "./dom.js";
import { kitBoolBadge, kitPanelHead, kitTable } from "./kit.js";

/* ═══ 求解器 ═══ */
export async function pageSolvers() {
  const v = T.$("view-solvers");
  v.innerHTML = help(`
    <li><b>求解器</b> = 实际执行电磁仿真的引擎。openEMS：免费开源 FDTD（当前可用）；Palace：有限元（未装则不可用）。</li>
    <li>HFSS 走商业 license，版本以实装为准（工程导入页留空=服务端缺省）；在「配方编辑」运行按钮旁或「优化调参」的 adapter 下拉中选择。</li>
    <li>「可视化 N 个」= 该求解器能产出的补充视图数量。</li>`) +
    "<h2 class='page'>求解器</h2>" + kitPanelHead("注册状态") + "<div id='sv-body' class='muted'>加载中...</div></div>";
  const d = await T.api("/api/solvers");
  const viz = await T.api("/api/solvers/viz");
  // A7-A ui-kit 试点：表壳单源（kitTable；empty:"" 保持空 tbody 等价）+
  // 可用性徽章单源（kitBoolBadge）
  T.$("sv-body").innerHTML =
    kitTable({
      columns: ["类型", "类", "可用", "可视化"], rows: d.solvers || [], empty: "",
      rowHtml: (s) =>
        `<tr><td><b>${esc(s.type)}</b></td><td class="muted">${esc(s.class)}</td><td>${kitBoolBadge(s.available, "可用", "不可用")}</td><td>${esc(s.n_visualizations)}</td></tr>`,
    }) +
    `<pre>${esc(JSON.stringify(viz, null, 2))}</pre>`;
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 solversCtx ═══════════
   refresh=注册状态表重拉（pageSolvers 幂等——整页重建，无交互态/无轮询面，
   leave 不需要）。 */
export const solversCtx = {
  refresh: () => pageSolvers(),
};
