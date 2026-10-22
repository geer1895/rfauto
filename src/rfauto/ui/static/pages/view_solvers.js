/* rfauto 求解器页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）。
   i18n（发布前软编码批 S2 全清）：help 块分段 t()、标题/面板头/表头/
   可用性徽章/加载态全迁词表（solvers.* 键域，zh 与旧字面逐字节同、en 新增）；
   表数据（type/class 列值）照旧 esc——API 动态数据不迁（数据非文案）。 */

import { T } from "./context.js";
import { esc, help } from "./dom.js";
// i18n（发布前软编码批 S2）：动态重建页（无壳缓存），文案一律 t() 渲染期
// 烘焙；applyI18nRoot 首扫兜 data-i18n 标注（幂等）。
import { t, applyI18nRoot } from "./i18n.js";
import { kitBoolBadge, kitPanelHead, kitTable } from "./kit.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 2 点）——
// 数据面全页（注册状态/viz 清单）接 viewSignal("solvers") 切页收束 + aborted
// 短路（在途拉取不再写隐藏区）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ 求解器 ═══ */
export async function pageSolvers() {
  const v = T.$("view-solvers");
  v.innerHTML = help(`
    <li><b>${t("solvers.help_1_core")}</b>${t("solvers.help_1_tail")}</li>
    <li>${t("solvers.help_2")}</li>
    <li>${t("solvers.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='solvers.title'>${t("solvers.title")}</span></h2>` +
    kitPanelHead(t("solvers.reg_title")) +
    `<div id='sv-body' class='muted'>${t("solvers.loading")}</div></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（幂等，动态容器走 t() 烘焙）
  const d = await apiFetch("/api/solvers", { signal: viewSignal("solvers") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const viz = await apiFetch("/api/solvers/viz", { signal: viewSignal("solvers") });
  if (viz.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  // A7-A ui-kit 试点：表壳单源（kitTable）+ 可用性徽章单源（kitBoolBadge）
  // R4：去掉 empty:"" 显式空 tbody——注册表为空时出缺省空态行（暂无数据），
  // 不再渲染无声空表。
  T.$("sv-body").innerHTML =
    kitTable({
      columns: [t("solvers.th_type"), t("solvers.th_class"), t("solvers.th_available"), t("solvers.th_viz")],
      rows: d.solvers || [],
      rowHtml: (s) =>
        `<tr><td><b>${esc(s.type)}</b></td><td class="muted">${esc(s.class)}</td><td>${kitBoolBadge(s.available, t("solvers.badge_available"), t("solvers.badge_unavailable"))}</td><td>${esc(s.n_visualizations)}</td></tr>`,
    });
    // 人性化三批（2026-10-19 审计 ✗3）：表尾裸 JSON <pre> 调试遗物删除——
    // /api/solvers/viz 整包响应曾以 JSON.stringify 直渲染给用户（数百行
    // 无格式原文面客）；注册表数据已在上方 kitTable 结构化呈现。viz 拉取
    // 暂保留（卸载它需同步清 scripts/check_ui_contracts.py 未传参数豁免
    // 表 /api/solvers/viz#solver 条目=本席禁改面——留待后续席一并清偿）。
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 solversCtx ═══════════
   refresh=注册状态表重拉（pageSolvers 幂等——整页重建，无交互态/无轮询面，
   leave 不需要）。 */
export const solversCtx = {
  refresh: () => pageSolvers(),
};
