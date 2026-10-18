/* rfauto Run 详情页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   S 参数交互曲线 + 3D 模型 + 产物清单 + 配方快照。 */

import { releaseWebGLIn, sparamChartProps } from "./charts.js"; // UI-R5：S 参数 props 走 charts 层选项工厂
import { S, T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal）
import { apiFetch, viewSignal } from "./api.js";
import { esc } from "./dom.js";
import { bindClickRows, kitApplyClickRowAttrs, kitSkeleton } from "./kit.js";
import { showPage } from "./router.js";

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
      v.innerHTML = `<h2 class='page'>Run 详情</h2>
        <div class='panel'><span class="empty-ico" aria-hidden="true">◉</span>
        <span class="empty-txt"><span class='muted'>未指定 run——请从「Run 列表」或总览点选，或用 #/detail/&lt;run_id&gt; 深链直达。</span></span>
        <button class="minor" id="detail-goto-runs" style="margin-left:8px">去 Run 列表</button></div>`;
    const go = T.$("detail-goto-runs");
    if (go) go.onclick = () => showPage("runs");
    return;
  }
  S.currentRunId = id;
  if (!v.innerHTML)
    v.innerHTML = `<h2 class='page'>Run 详情 <small id='detail-id'></small></h2>
      <div class='panel' id='detail-head'></div>
      <div class='grid2'>
        <div class='panel'><b class='title'>S 参数（图例点击切换分量；滚轮缩放、悬停读数）</b>
          <div id='splot-echart'></div></div>
        <div class='panel'><b class='title'>3D 模型</b><div id='detail-3d'></div></div>
      </div>
      <div class='panel'><b class='title'>产物清单</b><table id='files-table'><thead><tr><th scope="col">文件</th><th scope="col">大小</th></tr></thead><tbody></tbody></table></div>
      <div class='panel'><b class='title'>配方快照</b><pre id='detail-recipe'></pre></div>`;
  // A8-A（R6 审计 P-2）：openRun 拉取骨架屏——首建壳即铺占位（shimmer 条，
  // reduced-motion 降级静态灰块）；数据到达后成功徽章/错误面板各自替换。
  const skHead = T.$("detail-head");
  if (skHead)
    skHead.innerHTML = `<div class="skeleton-wrap" role="status" aria-label="run 数据加载中">` + kitSkeleton(4) + `</div>`;
  const d = await apiFetch("/api/runs/" + id, { signal: viewSignal("detail") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  if (!d.ok) {
    // W7-C（R1 P1-6）：失败不只弹 toast——详情头写内联错误面板（含 run_id
    // 与重试钮），页面不再停留骨架空壳（msg 同步保留，双通道可见）
    T.msg((d.errors || []).join("; "), false);
    T.$("detail-head").innerHTML =
      `<span class="badge err">加载失败</span> <code>${esc(id)}</code>` +
      ` <span class="muted">${esc((d.errors || []).join("; "))}</span>` +
      ` <button class="minor" id="detail-retry">重试</button>`;
    const retry = T.$("detail-retry");
    if (retry) retry.onclick = () => showRun(id);
    return;
  }
  T.$("detail-id").textContent = d.run_id;
  const m = d.metrics || {};
  T.$("detail-head").innerHTML =
    Object.entries(m).map(([k, v2]) =>
      `<span class="badge muted" style="margin-right:8px">${esc(k)}: <b style="color:var(--fg)">${typeof v2 === "number" ? v2.toFixed(4) : esc(typeof v2 === "object" && v2 !== null ? JSON.stringify(v2) : v2)}</b></span>`).join("");
  const ftb = T.$("files-table").tBodies[0];
  ftb.innerHTML = "";
  for (const f of d.files || []) {
    const tr = document.createElement("tr");
    const kb = f.size_bytes > 1048576 ? (f.size_bytes / 1048576).toFixed(1) + " MB"
      : (f.size_bytes / 1024).toFixed(1) + " KB";
    tr.innerHTML = `<td>${esc(d.run_dir)}/${esc(f.path)}</td><td>${kb}</td>`;
    ftb.appendChild(tr);
  }
  T.$("detail-recipe").textContent = d.recipe_snapshot || "(无快照)";

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
    T.$("splot-echart").innerHTML = '<span class="muted">无 Touchstone（fake 通道），曲线图：</span>';
    for (const f of d.figs || []) {
      const img = document.createElement("img");
      img.src = "/" + f;
      img.style.cssText = "max-width:100%;display:block;margin:6px 0;border-radius:4px;cursor:zoom-in";
      img.dataset.fig = f;
      // UI-R4 a11y：可点图=交互元素，role=button+tabindex+aria-label 同 kit
      // 口径（灯箱放大动作读屏可闻；Enter/Space 激活在下方 bindClickRows）
      kitApplyClickRowAttrs(img, { label: "放大查看曲线图：" + f.split("/").pop() });
      T.$("splot-echart").appendChild(img);
    }
    // UI-R4：click 与 Enter/Space 同一激活（kit 单源；图片不落手写 keydown）
    bindClickRows(T.$("splot-echart"),
      (img) => T.lightboxImg("/" + img.dataset.fig, img.dataset.fig.split("/").pop()),
      "img[data-fig]");
  }
  releaseWebGLIn(T.$("detail-3d")); // P0-4 防御式：弃置上一代 WebGL 上下文（接口诉求见 releaseWebGLIn）
  T.drawBoxes(T.$("detail-3d"), d.model3d || { ok: false, errors: ["该 run 无可渲染的 3D 模板"] });
}

/* ═══ R-1（aurora_e W2-S7）：PageContext 增量钩子 detailCtx ════════════
   refresh=当前 run 重渲（showRun 幂等整页刷新——骨架屏→数据替换同链路；
   S.currentRunId 为空时走未指定 run 空态引导，与 showPage 回退行为一致）；
   无轮询/无定时器面，leave 不需要（SSE 收束由 router._sseLeavePage 单源）。 */
export const detailCtx = {
  refresh: () => showRun(S.currentRunId),
};
