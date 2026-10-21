/* rfauto 优化调参页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）：
   trial 实时监控（SSE 推送 + 3s 轮询回退，两链路经 lifecycle/sse 单源
   托管）。
   R-1（架构批 W2-S7）：PageContext 增量钩子 tuneCtx（注册在 pages.js →
   router.js PAGE_CTX）——refresh=立即拉一次状态+trials（palette 刷新局部
   化，不重进页面）；leave=_pollStop 非终态离页停表（fn 保留，重进
   _pollRegister 先停旧再挂新；终态停仍走 tuneRefresh 内 _pollStop(name,true)
   语义不变）。拉取+渲染体提升到模块级（零闭包依赖——只消费 T/单源模块
   绑定），供 ctx 与页内轮询/SSE kick 三方共用同一函数体。 */

import { plotCardCached } from "./charts.js";
import { T } from "./context.js";
import { esc, help } from "./dom.js";
// i18n（架构批 W4-S1 壳层迁移 + 发布令 S3 残量清）：壳静态标签
// data-i18n+首扫、help 块分段 t()、动态串（状态行/空态/公告/aria）t() 烘焙
// ——trial 表体/结果 JSON 纯数据面不迁（数据插值仍在词表外 esc）。
import { t, applyI18nRoot } from "./i18n.js";
import { kitEmptyState, kitPanelHead } from "./kit.js";
import { _pollRegister, _pollStop, _pollVisible } from "./polling.js";
import { _SSE, _sseSubscribe, ssePollSuppressed } from "./sse.js";
// P8-9（架构批 W3-S9，R1 §面4）：T.api→apiFetch 统一请求层（本页 4 点）——
// 轮询/SSE 共用拉取体（tuneRefresh/renderTrials）与配方信息数据面接
// viewSignal("tune") 切页收束 + aborted 短路（离页在途轮询不再写隐藏区，
// 与 _pollVisible 离页守卫互补：定时器保留、在途请求即收）；startTune
// 动作 POST 保持无 signal（用户显式动作不因切页取消）。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ 优化调参 ═══ */

export async function pageTune() {
  const v = T.$("view-tune");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>adapter</b>${t("tune.help_1")}</li>
      <li><b>trials</b>${t("tune.help_2")}</li>
      <li><b>${t("tune.help_3_core")}</b>${t("tune.help_3_tail")}</li>
      <li>${t("tune.help_4_lead")}<b>best_params</b>${t("tune.help_4_tail")}</li>
      <li>${t("tune.help_5")}</li>`) +
    `<h2 class='page'><span data-i18n='tune.title'>${t("tune.title")}</span> <small data-i18n='tune.subtitle'>${t("tune.subtitle")}</small></h2>
      <div class='panel'><div class='toolbar'>
        ${t("tune.label_recipe")}<input id='tune-path' size='36' value='recipes/wilkinson_pd_v1.yaml'>
        adapter: <select id='tune-adapter'><option>fake</option><option>hfss</option><option>openems</option></select>
        trials: <input id='tune-trials' size='4' value='30'>
        sampler: <select id='tune-sampler'><option>tpe</option><option>cmaes</option></select>
        ${t("tune.label_multi")}<input type='checkbox' id='tune-multi'>
        <button class='act' id='tune-go' data-i18n='tune.start'>${t("tune.start")}</button>
        <span id='tune-spin'></span>
      </div><div id='tune-recipe-info' class='muted' style="margin-top:6px"></div></div>
      ${kitPanelHead(t("tune.result_title"), "", "id='tune-result' style='display:none'")}<pre id='tune-result-pre'></pre></div>
      <div class='panel'><b class='title' data-i18n='tune.trials_title'>${t("tune.trials_title")}</b>
        <div id='tune-trials-info' class='muted'></div>
        <div id='tune-trials-chart'></div>
        <table id='tune-trials-table'><thead><tr><th scope="col">#</th><th scope="col">cost</th><th scope="col">${t("tune.th_params")}</th><th scope="col">${t("tune.th_metrics")}</th></tr></thead><tbody></tbody></table></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W4-S1；幂等，动态容器走 t() 烘焙）
  T.$("tune-go").onclick = startTune;
  T.$("tune-path").onchange = showRecipeInfo;
  _pollRegister("tune", "tune", pollTune, 3000); // P2-13：轮询托管（进页即拉/离页守卫/隐藏暂停）
  showRecipeInfo();

  async function showRecipeInfo() {
    const d = await apiFetch("/api/recipes", { signal: viewSignal("tune") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const r = (d.recipes || []).find((x) => x.path === T.$("tune-path").value.trim());
    T.$("tune-recipe-info").innerHTML = r
      ? `${t("tune.sel_lead")}<b>${esc(r.model)}</b>${t("tune.sel_sep")}${esc(r.n_params)}${t("tune.sel_params")}${esc(r.n_objectives)}${t("tune.sel_obj")}${esc(JSON.stringify(r.freq_range))}${t("tune.sel_tail")}`
      : t("tune.path_not_in_catalog");
  }
  async function startTune() {
    const r = await apiFetch("/api/tune/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: T.$("tune-path").value.trim(),
                             adapter: T.$("tune-adapter").value,
                             max_trials: parseInt(T.$("tune-trials").value) || 30,
                             sampler: T.$("tune-sampler").value }),
      timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：调参启动分钟级
    });
    if (!r.ok) return T.msg(r.error, false);
    T.msg(t("tune.started"), true);
  }
  async function pollTune() {
    if (!_pollVisible("tune")) return; // P2-13：当前页+可见性双守卫（跳过 fetch，定时器保留）
    if (ssePollSuppressed(_SSE.tune)) return; // A6-A：SSE 流活跃——定时器保留、回调跳过降负载（断流自然回退轮询）
    await tuneRefresh();
  }
}

/* ═══ R-1（W2-S7）：模块级拉取+渲染体与 PageContext ═══════════════════
   tuneRefresh/renderTrials 自 pageTune 内提升（逐字节搬移；二者只消费
   模块级绑定 T/_pollStop/_sseSubscribe 等，零闭包依赖）。 */

/* A6-A：轮询回调与 SSE 推送共用的拉取+渲染体（幂等整页刷新）——SSE
   kick（含 end/error 帧的末次刷新）与 palette 刷新（tuneCtx.refresh）也走
   这里，终态停与结果面板逻辑同款。 */
/* W5-S23：调参运行态记忆（读屏公告的变迁检测面——running→终态边沿一次） */
let _tuneWasRunning = false;
async function tuneRefresh() {
  const st = await apiFetch("/api/tune/status", { signal: viewSignal("tune") });
  if (st.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  T.$("tune-spin").innerHTML = st.running ? "<span class='spin'></span>" + t("tune.running") : "";
  T.$("tune-go").disabled = !!st.running;
  // W5-S23（深审 b 面）：调参终态读屏公告——3s 轮询/SSE 刷 DOM 静默，
  // running→终态的边沿经 T.announce 播报一次（app.js 单源 live region；
  // T.announce 缺席=异常部署静默，#105 best-effort）。
  const wasRunning = _tuneWasRunning;
  _tuneWasRunning = !!st.running;
  if (wasRunning && !st.running && (st.result || st.error))
    announceTuneEnd(st);
  if (!st.running && (st.result || st.error)) {
    _pollStop("tune", true); // 终态停：清 fn，恢复可见不得复活已完成的轮询
    T.$("tune-result").style.display = "";
    if (st.error) T.$("tune-result-pre").textContent = t("tune.error_prefix") + st.error;
    else T.$("tune-result-pre").textContent = JSON.stringify(st.result, null, 2);
  }
  renderTrials(st);
}

/* W5-S23：终态公告文案（error/result 分支；函数独立=纯文案面 node 可测）。 */
function announceTuneEnd(st) {
  try {
    if (typeof T.announce !== "function") return;
    T.announce(st.error ? t("tune.announce_error") : t("tune.announce_done"));
  } catch { /* 公告面缺席不阻主路径 */ }
}

// trial 级实时监控：读 runs/<run_id>/trials/*.json（服务端聚合）
async function renderTrials(st) {
  const info = T.$("tune-trials-info");
  if (!info) return;
  const d = await apiFetch("/api/tune/trials", { signal: viewSignal("tune") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const trials = d.trials || [];
  if (d.run_id) _sseSubscribe("tune", d.run_id, tuneRefresh, "tune"); // A6-A：有 run 即订阅进度流（幂等；trial 推送期轮询让位）
  if (!trials.length) {
    // A8-A（R6 审计 P-3）：空态三件式——动作钮转触既有「启动调参」（tune-go）
    info.innerHTML = kitEmptyState(t("tune.empty_hint"),
      { icon: "⚙", label: t("tune.start_action"), id: "tune-empty-go" });
    const teg = T.$("tune-empty-go");
    const tgo = T.$("tune-go");
    if (teg && tgo) teg.onclick = () => tgo.click();
    return;
  }
  info.innerHTML = `run <b>${esc(d.run_id)}</b>${t("tune.trials_done")}${trials.length}${t("tune.trials_count")}`
    + (st?.running ? " · <span class='spin'></span>" + t("tune.in_progress") : "");
  // 收敛曲线（cost 随 trial）——PR-3 PlotCard convergence 模式：
  // best-so-far 阶梯线 + 终值 markLine + 末点（option 为声明增量）。
  // P0-5：经 plotCardCached 容器级复用（3s 轮询不再每拍新 init+新监听）
  plotCardCached(T.$("tune-trials-chart"), {
    series: [{
      x: trials.map((t) => t.trial_number),
      y: trials.map((t) => t.cost),
      name: "cost",
    }],
    mode: "convergence",
    height: "220px", xlabel: "trial", ylabel: "cost",
    exportName: "tune-cost-convergence",
    ariaLabel: t("tune.chart_aria"),
  });
  // 最近 12 条（新→旧）
  const tb = T.$("tune-trials-table").tBodies[0];
  tb.innerHTML = trials.slice(-12).reverse().map((t) => {
    const params = Object.entries(t.params || {})
      .map(([k, v]) => `${esc(k)}=${typeof v === "number" ? v.toFixed(3) : esc(v)}`).join("  ");
    const metrics = Object.entries(t.metrics || {})
      .map(([k, v]) => `${esc(k)}=${typeof v === "number" ? v.toFixed(3) : esc(v)}`).join("  ");
    return `<tr><td>${esc(t.trial_number)}</td><td>${esc(typeof t.cost === "number" ? t.cost.toFixed(4) : "-")}</td>
      <td class="muted">${params}</td><td class="muted">${metrics}</td></tr>`;
  }).join("");
}

/* R-1（W2-S7）PageContext：refresh=立即拉一次状态+trials（tuneRefresh
   幂等，palette 刷新不再整页重进）；leave=_pollStop 非终态（离页停表，
   fn 保留——重进页 _pollRegister 先停旧再挂新；终态语义在 tuneRefresh
   内 _pollStop(name,true) 不变）。 */
export const tuneCtx = {
  refresh: () => tuneRefresh(),
  leave: () => _pollStop("tune"),
};
