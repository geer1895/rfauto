/* rfauto Run 详情页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   S 参数交互曲线 + 3D 模型 + 产物清单 + 配方快照。
   W2-S3（aurora_i 采纳 #3）：失败 run "一键查看诊断"节（failure_context
   诊断包读面，缺包整节隐没；摘要 chips 词表化，全文 JSON 折叠展示）。 */

import { releaseWebGLIn, sparamChartProps } from "./charts.js"; // UI-R5：S 参数 props 走 charts 层选项工厂
import { S, T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal）
import { apiFetch, viewSignal } from "./api.js";
import { esc, escAttr } from "./dom.js";
// i18n（aurora_f W6-S21 扩面页 3；W8-S32 批 3 补骨架 aria/fake 曲线引导/
// 3D 空态/快照缺省四点；发布前软编码批 S2 残量清零=壳兜底文本 t() 烘焙+
// 曲线图 aria 前缀词表化）：壳静态标签 data-i18n+首扫（h2 内动态
// small#detail-id 不挂标注——静态文案包 span 防 textContent 重扫伤子元素）；
// 失败面板/重试钮随数据分支重建，文案 t() 渲染期烘焙。
import { t, applyI18nRoot, getLocale } from "./i18n.js";
import { bindClickRows, kitApiErrorHtml, kitApplyClickRowAttrs, kitSkeleton, metricBadgeHtml } from "./kit.js";
import { metricGlossaryMap } from "./metric_glossary.js";
import { showPage, noteCurrentRunId } from "./router.js";

/* ═══ W2-S3 失败诊断包（aurora_i 采纳 #3）：失败 run "一键查看诊断"节 ═══
   数据源=/api/runs/<id>/failure_context（failure_context_service 信封）；
   缺包（exists=false，非守护失败战役如实无包）→ 整节隐没；有包 → 摘要
   chips + 展开钮，全文 JSON 折叠 <pre>（首次展开才序列化）。context 全文
   为 API 数据照旧 esc/textContent（数据非文案不迁）。 */
async function loadFailureContext(id) {
  const panel = T.$("detail-failure");
  if (!panel) return;
  const f = await apiFetch("/api/runs/" + encodeURIComponent(id) +
    "/failure_context", { signal: viewSignal("detail") });
  if (f.aborted) return; // UI-R12：切页取消
  if (!f.ok || !f.exists) { panel.style.display = "none"; panel.innerHTML = ""; return; }
  const c = f.context || {};
  const lic = c.license || {};
  const mac = c.machine || {};
  const machineTxt = mac.skipped ? t("detail.failure_machine_local")
    : ((mac.name || mac.host || "—") + " · "
      + (mac.reachable ? t("detail.failure_machine_ok")
        : t("detail.failure_machine_down")));
  const licTxt = lic.skipped ? "SKIP" : (lic.verdict || "—");
  const chips = [
    t("detail.failure_captured_lead") + (c.captured_at || "—"),
    t("detail.failure_verdict_lead") + (c.verdict || "—"),
    t("detail.failure_license_lead") + licTxt,
    t("detail.failure_machine_lead") + machineTxt,
  ].map((s) => `<span class="badge muted" style="margin-right:8px">${esc(s)}</span>`).join("");
  panel.innerHTML =
    `<b class='title'>${t("detail.failure_title")}</b>
     <div style='margin:6px 0'>${chips}
       <button class='minor' id='failure-toggle' aria-label='${escAttr(t("detail.failure_toggle_aria"))}'>${t("detail.failure_view_btn")}</button></div>
     <pre id='failure-detail' style='display:none;max-height:360px;overflow:auto;white-space:pre-wrap;user-select:all'></pre>`;
  panel.style.display = "";
  const pre = T.$("failure-detail");
  T.$("failure-toggle").onclick = () => {
    const hidden = pre.style.display === "none";
    if (hidden && !pre.textContent) pre.textContent = JSON.stringify(c, null, 2);
    pre.style.display = hidden ? "" : "none";
    T.$("failure-toggle").textContent = hidden
      ? t("detail.failure_hide_btn") : t("detail.failure_view_btn");
  };
}

/* ═══ Run 详情（ECharts 交互曲线，图例切换分量）═══ */
export async function showRun(runId) {
  const id = runId || S.currentRunId;
  T.activate("detail");
  const v = T.$("view-detail");
  if (!id) {
    // aurora72 A4-C（R6 审计 R-2 冷加载白页清偿后半）：#/detail 裸页冷加载
    // 无 run 可显——铺诚实空态引导而非静默早退留白页；带参形态
    // #/detail/<id> 由路由分发器走 openRun（数据拉取+错误面板在主路径）。
    // A8-A（R6 审计 P-3）：空态三件式补形（图标锚+一句话+动作钮；钉面
    // id="detail-goto-runs" 与绑定形态原样保留——test_ui_routing 同笔）。
    if (!v.innerHTML)
      v.innerHTML = `<h2 class='page' data-i18n='detail.title'>${t("detail.title")}</h2>
        <div class='panel'><span class="empty-ico" aria-hidden="true">◉</span>
        <span class="empty-txt"><span class='muted' data-i18n='detail.empty_no_run'>${t("detail.empty_no_run")}</span></span>
        <button class="minor" id="detail-goto-runs" style="margin-left:8px" data-i18n='detail.goto_runs'>${t("detail.goto_runs")}</button></div>`;
    applyI18nRoot(v); // 壳静态标签首扫（W6-S21 扩面）
    const go = T.$("detail-goto-runs");
    if (go) go.onclick = () => showPage("runs");
    return;
  }
  noteCurrentRunId(id); // W6-S2：run 态写面唯一=router.js（原 S 直写第二写点收口）
  if (!v.innerHTML)
    v.innerHTML = `<h2 class='page'><span data-i18n='detail.title'>${t("detail.title")}</span> <small id='detail-id'></small></h2>
      <div class='panel' id='detail-head'></div>
      <div class='panel' id='detail-failure' style='display:none'></div>
      <div class='grid2'>
        <div class='panel'><b class='title' data-i18n='detail.sparams_title'>${t("detail.sparams_title")}</b>
          <div id='splot-echart'></div></div>
        <div class='panel'><b class='title' data-i18n='detail.model3d'>${t("detail.model3d")}</b><div id='detail-3d'></div></div>
      </div>
      <div class='panel'><b class='title' data-i18n='detail.files_title'>${t("detail.files_title")}</b><table id='files-table'><thead><tr><th scope="col" data-i18n='detail.th_file'>${t("detail.th_file")}</th><th scope="col" data-i18n='detail.th_size'>${t("detail.th_size")}</th></tr></thead><tbody></tbody></table></div>
      <div class='panel'><b class='title' data-i18n='detail.recipe_title'>${t("detail.recipe_title")}</b><pre id='detail-recipe'></pre></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W6-S21 扩面）
  // A8-A（R6 审计 P-2）：openRun 拉取骨架屏——首建壳即铺占位（shimmer 条，
  // reduced-motion 降级静态灰块）；数据到达后成功徽章/错误面板各自替换。
  const skHead = T.$("detail-head");
  if (skHead)
    skHead.innerHTML = `<div class="skeleton-wrap" role="status" aria-label="${t("detail.loading_aria")}">` + kitSkeleton(4) + `</div>`;
  const d = await apiFetch("/api/runs/" + id, { signal: viewSignal("detail") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  if (!d.ok) {
    // W7-C（R1 P1-6）：失败不只弹 toast——详情头写内联错误面板（含 run_id
    // 与重试钮），页面不再停留骨架空壳（msg 同步保留，双通道可见）。
    // W6-S21：面板文案随失败分支重建，t() 渲染期烘焙（词表 detail.*）。
    // 人性化三批（2026-10-19 审计 ✗1/✗2）：①错误分支同步把 h2 动态段
    // （small#detail-id）置为"加载失败"——不再残留上一个 run id 造成
    // run 间误读；②错误呈现收编 kitApiErrorHtml 统一错误卡（信封解析走
    // errorText 单源——errors[]/error/reason 全形态覆盖，含 W2-S2 种子
    // run 无 meta 时列表/详情口径差的 ok:false 信封），run_id 内联可见、
    // 重试钮保留（钉面 test_w7c_ui_p2_sweep 同笔更新）。
    T.msg((d.errors || []).join("; "), false);
    const idEl = T.$("detail-id");
    if (idEl) idEl.textContent = t("detail.load_failed");
    T.$("detail-head").innerHTML =
      kitApiErrorHtml(d, { title: t("detail.load_failed"), hint: "" }) +
      ` <code>${esc(id)}</code>` +
      ` <button class="minor" id="detail-retry">${t("detail.retry")}</button>`;
    const retry = T.$("detail-retry");
    if (retry) retry.onclick = () => showRun(id);
    return;
  }
  T.$("detail-id").textContent = d.run_id;
  const m = d.metrics || {};
  // W2-S2（aurora_i，R3 M2）指标词典悬浮说明：词条在场→data-tip 白话+
  // 健康判据+坑号 & 判据着色（达标 var(--ok)/未达标 var(--err)）；词典
  // 加载失败=空映射→逐键降级原徽章形态（metricBadgeHtml 单源，#105）。
  const glossary = await metricGlossaryMap();
  const loc = getLocale();
  T.$("detail-head").innerHTML =
    Object.entries(m).map(([k, v2]) =>
      metricBadgeHtml(k, v2, glossary[k], loc)).join("");
  const ftb = T.$("files-table").tBodies[0];
  ftb.innerHTML = "";
  for (const f of d.files || []) {
    const tr = document.createElement("tr");
    const kb = f.size_bytes > 1048576 ? (f.size_bytes / 1048576).toFixed(1) + " MB"
      : (f.size_bytes / 1024).toFixed(1) + " KB";
    tr.innerHTML = `<td>${esc(d.run_dir)}/${esc(f.path)}</td><td>${kb}</td>`;
    ftb.appendChild(tr);
  }
  T.$("detail-recipe").textContent = d.recipe_snapshot || t("detail.recipe_none");

  if ((d.sparams || []).length) {
    // PR-3 PlotCard 换壳 + crosshair；UI-R5：props 预设走 charts 层选项工厂
    // sparamChartProps（dB 档单源——ylabel/crosshair/zoom/GHz 横轴收编彼处）
    T.plotCard(T.$("splot-echart"), sparamChartProps({
      mode: "db",
      curves: d.sparams.map((c) => ({
        name: c.name || c.file,
        freq_ghz: c.freq_ghz.map((f) => +f.toFixed(4)), y: c.db,
      })),
      height: "320px", exportName: "run-sparams",
    }));
  } else {
    // W8-S32 i18n 批 3：fake 通道引导文案 t() 烘焙（随数据分支重建）
    T.$("splot-echart").innerHTML = '<span class="muted">' + t("detail.no_touchstone") + "</span>";
    for (const f of d.figs || []) {
      const img = document.createElement("img");
      img.src = "/" + f;
      img.style.cssText = "max-width:100%;display:block;margin:6px 0;border-radius:4px;cursor:zoom-in";
      img.dataset.fig = f;
      // UI-R4 a11y：可点图=交互元素，role=button+tabindex+aria-label 同 kit
      // 口径（灯箱放大动作读屏可闻；Enter/Space 激活在下方 bindClickRows）
      // i18n（S2）：aria 文案段走词表（detail.fig_zoom_lead），文件名为 API
      // 数据照旧模板外拼（setAttribute 纯文本零转义需求）。
      kitApplyClickRowAttrs(img, { label: t("detail.fig_zoom_lead") + f.split("/").pop() });
      T.$("splot-echart").appendChild(img);
    }
    // UI-R4：click 与 Enter/Space 同一激活（kit 单源；图片不落手写 keydown）
    bindClickRows(T.$("splot-echart"),
      (img) => T.lightboxImg("/" + img.dataset.fig, img.dataset.fig.split("/").pop()),
      "img[data-fig]");
  }
  releaseWebGLIn(T.$("detail-3d")); // P0-4 防御式：弃置上一代 WebGL 上下文（接口诉求见 releaseWebGLIn）
  T.drawBoxes(T.$("detail-3d"), d.model3d || { ok: false, errors: [t("detail.no_model3d")] });
  await loadFailureContext(id); // W2-S3：失败诊断包节（缺包整节隐没）
}

/* ═══ R-1（aurora_e W2-S7）：PageContext 增量钩子 detailCtx ════════════
   refresh=当前 run 重渲（showRun 幂等整页刷新——骨架屏→数据替换同链路；
   S.currentRunId 为空时走未指定 run 空态引导，与 showPage 回退行为一致）；
   无轮询/无定时器面，leave 不需要（SSE 收束由 router._sseLeavePage 单源）。 */
export const detailCtx = {
  refresh: () => showRun(S.currentRunId),
};
