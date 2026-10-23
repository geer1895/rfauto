/* rfauto Run 历史页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   指标筛选 + 可排序表 + 骨架屏/空态。 */

import { T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal）
import { apiFetch, viewSignal } from "./api.js";
import { esc, help } from "./dom.js";
// i18n（aurora_f W6-S21 扩面页 2）：壳静态标签 data-i18n+首扫；筛选空态随
// render() 重建，文案 t() 渲染期烘焙（i18n.js 头注纪律）。
import { t, applyI18nRoot, getLocale } from "./i18n.js";
import { bindClickRows, bindEmptyStates, kitApplyClickRowAttrs, kitBadgeCls, kitEmptyState, kitSkeletonRows, metricValueHtml } from "./kit.js";
import { metricGlossaryMap, mountMetricTips } from "./metric_glossary.js";
import { openRun } from "./router.js";
import { makeSortable } from "./sortable.js";

/* ═══ Run 历史（指标筛选）═══ */

/* W5-S17（aurora_f，R1 §面3 虚拟滚动 watch 激活）：行数自适应降级阈值。
   R1 盘点结论「limit=500 现状可接受、>1000 再复用 renderVirtualList」的本
   意=拿数据定案，真机实测（Chrome 155，500 行×6 列）：JS+DOM 全量重建
   8.2ms、稳态脏重排 ~21ms、滚动 180fps 零掉帧——本机流畅；故按"行数
   自适应降级"落守卫：筛选后行数 >200（R1 审计建议档）时表挂 .vrows 类
   （CSS content-visibility 规则见 index.html——Chrome 155 在 tr 上实测
   无感收益但零风险，规则作为渐进增强与阈值挂点保留；不支持者忽略=
   旧行为）。≤阈值全量渲染旧形态逐字节不变；行数增长无界，>1000 行升级
   renderVirtualList 窗口化仍挂 watch（数据归档
   runs/aurora_f/w5s17_runs_vrows_measure.md）。 */
const VROWS_THRESHOLD = 200;

/* run 清单缓存（W6-S2 S 状态收编：原 S.allRuns 单模块私有键降级模块级
   ——属主=本模块，契约表见 context.js；进页重拉/筛选复用引用语义不变）。 */
let _allRuns = null;

export async function pageRuns() {
  const v = T.$("view-runs");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("runs.help_1")}</li>
      <li>${t("runs.help_2")}</li>`) +
    `<h2 class='page' data-i18n='runs.title'>${t("runs.title")}</h2>
      <div class='panel'><div class='toolbar'>
        <input id='f-text' size='18' placeholder='${t("runs.filter_placeholder")}' data-i18n-ph='runs.filter_placeholder'>
        <select id='f-adapter'><option value='' data-i18n='runs.all_channels'>${t("runs.all_channels")}</option><option>fake</option><option>openems</option><option>hfss</option></select>
        <span data-i18n='runs.s11_better_than'>${t("runs.s11_better_than")}</span> <input id='f-s11' size='8' placeholder='-20'> dB
        <button class='minor' id='f-clear' data-i18n='runs.clear'>${t("runs.clear")}</button>
        <span id='f-count' class='muted'></span>
      </div>
      <table id='runs-table' data-sortable><caption class="sr-only">${t("runs.caption")}</caption><thead>
        <tr><th scope="col">run_id</th><th scope="col" data-i18n='runs.th_time'>${t("runs.th_time")}</th><th scope="col">adapter</th><th scope="col" data-i18n='runs.th_inband_s11' data-mkey='s11_db_max_in_band'>${t("runs.th_inband_s11")}</th><th scope="col" data-i18n='runs.th_status'>${t("runs.th_status")}</th><th scope="col" data-i18n='runs.th_best_metric'>${t("runs.th_best_metric")}</th></tr>
      </thead><tbody></tbody></table></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W6-S21 扩面）
  // W2-S2（aurora_i，R3 M2）：带内 S11 列头悬浮说明（data-mkey 挂点接线，
  // 词条缺席零触碰；best-effort 不阻列表主路径 #105）
  mountMetricTips(v).catch(() => { /* 说明层静默 */ });
  // A8-A（R6 审计 P-2）：首拉骨架屏——表体占位行（shimmer 条，reduced-motion
  // 降级静态灰块）；/api/runs 数据到达后 render() 整体替换。
  const skTable = T.$("runs-table");
  if (skTable && skTable.tBodies[0])
    skTable.tBodies[0].innerHTML = kitSkeletonRows(5, 6);
  // P8-7（aurora_f R1 §面3 P2 级）：显式 limit=500——裸调 /api/runs 落服务端
  // 缺省 50（runs/ 实存 3255 条目），历史页只见最近 50 条口径失真；对齐
  // view_sparams.js:37 同款已修形态（sparams 页 W7 P2-1 先例）。真分页
  // （服务端 total+翻页条）挂 R1 watch，500 内缓行。
  const data = await apiFetch("/api/runs?limit=500", { signal: viewSignal("runs") });
  if (data.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  _allRuns = data.runs || [];
  // W2-S2（aurora_i，R3 M2）：词典词条会话级缓存（失败=空映射→单元格
  // 中性降级原文本）；render 闭包消费，debounce 重绘同源。
  const glossary = await metricGlossaryMap();
  const gEntry = glossary["s11_db_max_in_band"];
  const gLocale = getLocale();
  const render = () => {
    const ft = T.$("f-text").value.trim().toLowerCase();
    const fa = T.$("f-adapter").value;
    const fs = parseFloat(T.$("f-s11").value);
    const rows = _allRuns.filter((r) => {
      if (ft && !(r.run_id || "").toLowerCase().includes(ft)) return false;
      if (fa && r.adapter !== fa) return false;
      const m11 = r.metrics?.s11_db_max_in_band;
      if (!isNaN(fs) && !(typeof m11 === "number" && m11 <= fs)) return false;
      return true;
    });
    T.$("f-count").textContent = `${rows.length} / ${_allRuns.length}`;
    const tb = T.$("runs-table").tBodies[0];
    tb.innerHTML = "";
    // W5-S17：行数自适应降级（>VROWS_THRESHOLD 挂 .vrows 启 content-visibility
    // 跳渲染；tbody 元素跨 innerHTML 换血存活，类随筛选结果每拍重评）
    tb.classList.toggle("vrows", rows.length > VROWS_THRESHOLD);
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      // R3 人性化三批：行左缘 3px 状态竖线（绿=done/pass 红=fail 灰=运行中
      // /未知；kitBadgeCls 单源映射，tr class 属性面零 DOM 结构变化——状态
      // 徽章仍恒 muted 淡显，行色条是独立视觉面不翻既有"状态列次要信息"账）
      tr.classList.add("st-" + kitBadgeCls(r.status || "done"));
      const metrics = r.metrics
        ? Object.entries(r.metrics).map(([k, v2]) => `${esc(k)}=${typeof v2 === "number" ? v2.toFixed(3) : esc(v2)}`).join(" ")
        : "";
      const m11 = r.metrics?.s11_db_max_in_band;
      // W2-S2（aurora_i，R3 M2）：带内 S11 单元悬浮+判据着色（词条缺席
      // →中性原文本；fmt=2 位小数+dB 同原口径）
      const m11Cell = metricValueHtml(gEntry, m11,
        (x) => x.toFixed(2) + " dB", gLocale);
      tr.innerHTML = `<td>${esc(r.run_id || "")}</td><td>${esc(r.timestamp || r.ts || "")}</td><td>${esc(r.adapter || "")}</td><td>${m11Cell}</td><td>${T.badge(r.status || "done", "muted")}</td><td class="muted">${metrics}</td>`;
      tr.dataset.id = r.run_id || ""; // UI-R4：激活回调按行取 id（bindClickRows 单入口）
      // UI-R4：键盘可达三件套（tr 行 role:null 保 row/cell 语义；
      // aria-label 行动作读屏可闻——run_id 经 setAttribute 字面量语境）
      kitApplyClickRowAttrs(tr, { role: null, label: t("runs.open_detail_aria") + (r.run_id || "") });
      if (tr.children[0]) tr.children[0].title = r.run_id || ""; // W7-C：截断列悬停见全名
      tb.appendChild(tr);
    }
    // A4-C：单入口收编（hash 深链同步，R6 R-2）+ UI-R4：click/Enter/Space 同一激活
    bindClickRows(tb, (tr) => openRun(tr.dataset.id), "tr.clickable");
    if (!rows.length) {
      if (!_allRuns.length) {
        // R4 空态三件式（零记录 vs 筛选零命中分流）：一句话现状 + 下一步
        // （跳转钮去 Tuning + CLI 命令行示例 <code> 段——结构留模板、文案
        // 进词表，词表值零 HTML 纪律不变；命令行为 ASCII 协议字面）。
        tb.innerHTML = `<tr><td colspan="6">` + kitEmptyState(
          t("runs.empty_no_runs") +
          "<code>rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake</code>",
          { icon: "☰", label: t("runs.goto_tune"), view: "tune" },
        ) + `</td></tr>`;
        bindEmptyStates(tb);
        return;
      }
      // A8-A（R6 审计 P-3）：筛选空态三件式（表体形态=colspan 行包 empty-state；
      // 动作钮转触既有「清除筛选」逻辑）。W6-S21：文案随 render() 重建，走
      // t() 渲染期烘焙（词表 runs.empty_filter / runs.clear_filter）。
      tb.innerHTML = `<tr><td colspan="6">` + kitEmptyState(t("runs.empty_filter"),
        { icon: "☰", label: t("runs.clear_filter"), id: "runs-empty-clear" }) + `</td></tr>`;
      const rc = T.$("runs-empty-clear");
      const fc = T.$("f-clear");
      if (rc && fc) rc.onclick = () => fc.click();
    }
    // aurora36 W3-B（P1-7）：筛选重渲染后重放当前排序（makeSortable 幂等）
    const sruns = makeSortable(T.$("runs-table"));
    if (sruns) sruns.refresh();
  };
  // P8-7 同笔（R1 §面3）：limit=500 下筛选每键全表重绘——文本输入 120ms
  // debounce 防连击卡顿（select 下拉与 s11 输入的 onchange 仍即时）；
  // 视图函数作用域计时器，离页误发一拍 render 写隐藏区无副作用（数据
  // 引用 _allRuns 不变，view_playground.js debounce 同款纪律）。
  let _filterTimer = 0;
  ["f-text", "f-adapter", "f-s11"].forEach((id) => {
    T.$(id).oninput = () => {
      clearTimeout(_filterTimer);
      _filterTimer = setTimeout(render, 120);
    };
    T.$(id).onchange = render;
  });
  T.$("f-clear").onclick = () => {
    T.$("f-text").value = ""; T.$("f-adapter").value = ""; T.$("f-s11").value = "";
    render();
  };
  render();
}

/* ═══ R-1（aurora_e W2-S7）：PageContext 增量钩子 runsCtx ══════════════
   refresh=数据重拉（pageRuns 幂等——壳判 innerHTML 已在即跳过、筛选控件
   值保留、表体经骨架屏→render() 替换；apiFetch 带 viewSignal("runs") 切页
   取消语义随行）。无轮询/定时器面，leave 不需要。 */
export const runsCtx = {
  refresh: () => pageRuns(),
};
