/* rfauto 优化调参页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   trial 实时监控（SSE 推送 + 3s 轮询回退，两链路经 lifecycle/sse 单源
   托管）。
   R-1（aurora_e W2-S7）：PageContext 增量钩子 tuneCtx（注册在 pages.js →
   router.js PAGE_CTX）——refresh=立即拉一次状态+trials（palette 刷新局部
   化，不重进页面）；leave=_pollStop 非终态离页停表（fn 保留，重进
   _pollRegister 先停旧再挂新；终态停仍走 tuneRefresh 内 _pollStop(name,true)
   语义不变）。拉取+渲染体提升到模块级（零闭包依赖——只消费 T/单源模块
   绑定），供 ctx 与页内轮询/SSE kick 三方共用同一函数体。
   UI 人性化席 R1（运行链，2026-10-19）：用户实测五修复——①默认 adapter=fake
   显式 selected+autocomplete=off（浏览器表单恢复曾把选择顶回 hfss）+旁注
   一行人话提示；②选真机通道即出预检卡（前置条件说在点「启动」之前）；
   ③失败不再甩裸 JSON——信封 errors 解析成错误卡（图标+标题+原文+建议，
   HFSS 未连接类错误译成动作指引+一键切回 fake），原文折叠保底；
   ④成功渲染结构化结果卡（best 参数表单位 best-effort 从 /api/recipe 取、
   cost/轮次统计/下一步按钮），原始 JSON 折叠不删；⑤启动钮 busy 三态
   （kitBtnBusy）。全部文案走 i18n（zh+en 同步）；服务端信封零改动——
   错误语义只在呈现层解决。 */

import { plotCardCached } from "./charts.js";
import { T } from "./context.js";
import { esc, errorText, fmtNum, help } from "./dom.js";
// i18n（aurora_h W4-S1 壳层迁移 + 发布令 S3 残量清）：壳静态标签
// data-i18n+首扫、help 块分段 t()、动态串（状态行/空态/公告/aria）t() 烘焙
// ——trial 表体/结果 JSON 纯数据面不迁（数据插值仍在词表外 esc）。
import { t, applyI18nRoot } from "./i18n.js";
import { kitBtnBusy, kitEmptyState, kitPanelHead } from "./kit.js";
import { _pollRegister, _pollStop, _pollVisible } from "./polling.js";
// R1：结果卡下一步按钮复用路由单源（view_recipe openRun 同款先例）。
import { openRun, showPage } from "./router.js";
import { _SSE, _sseSubscribe, ssePollSuppressed } from "./sse.js";
// P8-9（aurora_f W3-S9，R1 §面4）：T.api→apiFetch 统一请求层（本页 4 点）——
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
      <li>${t("tune.help_flow")}</li>
      <li>${t("tune.help_channel")}</li>
      <li>${t("tune.help_need")}</li>
      <li>${t("tune.help_read")}</li>
      <li>${t("tune.help_multi")}</li>`) +
    `<h2 class='page'><span data-i18n='tune.title'>${t("tune.title")}</span> <small data-i18n='tune.subtitle'>${t("tune.subtitle")}</small></h2>
      <div class='panel'><div class='toolbar'>
        ${t("tune.label_recipe")}<input id='tune-path' size='36' value='recipes/wilkinson_pd_v1.yaml'>
        ${t("tune.label_adapter")}<select id='tune-adapter' autocomplete='off'>
          <option value='fake' selected data-i18n='tune.opt_fake'>${t("tune.opt_fake")}</option>
          <option value='hfss' data-i18n='tune.opt_hfss'>${t("tune.opt_hfss")}</option>
          <option value='openems' data-i18n='tune.opt_openems'>${t("tune.opt_openems")}</option>
        </select>
        ${t("tune.label_trials")}<input id='tune-trials' size='4' value='30'>
        ${t("tune.label_sampler")}<select id='tune-sampler'><option>tpe</option><option>cmaes</option></select>
        ${t("tune.label_multi")}<input type='checkbox' id='tune-multi'>
        <button class='act' id='tune-go' data-i18n='tune.start'>${t("tune.start")}</button>
        <span id='tune-spin'></span>
      </div><div id='tune-recipe-info' class='muted' style="margin-top:6px"></div>
      <div id='tune-precheck' style="margin-top:6px"></div></div>
      ${kitPanelHead(t("tune.result_title"), "", "id='tune-result' style='display:none'")}<div id='tune-result-body'></div></div>
      <div class='panel'><b class='title' data-i18n='tune.trials_title'>${t("tune.trials_title")}</b>
        <div class='muted' style='font-size:12px' data-i18n='tune.trials_mech'>${t("tune.trials_mech")}</div>
        <div id='tune-trials-info' class='muted'></div>
        <div id='tune-trials-chart'></div>
        <table id='tune-trials-table'><thead><tr><th scope="col">#</th><th scope="col">cost</th><th scope="col">${t("tune.th_params")}</th><th scope="col">${t("tune.th_metrics")}</th></tr></thead><tbody></tbody></table></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W4-S1；幂等，动态容器走 t() 烘焙）
  T.$("tune-go").onclick = startTune;
  T.$("tune-path").onchange = showRecipeInfo;
  T.$("tune-adapter").onchange = renderPrecheck; // R1：换通道即出/收预检卡
  _pollRegister("tune", "tune", pollTune, 3000); // P2-13：轮询托管（进页即拉/离页守卫/隐藏暂停）
  showRecipeInfo();
  renderPrecheck();

  async function showRecipeInfo() {
    const d = await apiFetch("/api/recipes", { signal: viewSignal("tune") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const r = (d.recipes || []).find((x) => x.path === T.$("tune-path").value.trim());
    T.$("tune-recipe-info").innerHTML = r
      ? `${t("tune.sel_lead")}<b>${esc(r.model)}</b>${t("tune.sel_sep")}${esc(r.n_params)}${t("tune.sel_params")}${esc(r.n_objectives)}${t("tune.sel_obj")}${esc(JSON.stringify(r.freq_range))}${t("tune.sel_tail")}`
      : t("tune.path_not_in_catalog");
  }
  async function startTune() {
    const btn = T.$("tune-go");
    kitBtnBusy(btn, true, t("tune.start_busy")); // R1：启动钮 busy 三态（restore 在 tuneRefresh 终态/本函数失败分支）
    const r = await apiFetch("/api/tune/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: T.$("tune-path").value.trim(),
                             adapter: T.$("tune-adapter").value,
                             max_trials: parseInt(T.$("tune-trials").value) || 30,
                             sampler: T.$("tune-sampler").value }),
      timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：调参启动分钟级
    });
    if (!r.ok) {
      kitBtnBusy(btn, false);
      // R1：启动失败同样入错误卡（不再裸 toast JSON）——旧结果面板清场
      T.$("tune-result").style.display = "";
      T.$("tune-result-body").innerHTML = tuneErrorCard(r);
      bindErrorCardActions(r);
      T.msg(errorText(r), false);
      return;
    }
    T.msg(t("tune.started"), true);
    // R1：新一轮启动即收起旧结果面板（终态由轮询/SSE 重新呈现）
    T.$("tune-result").style.display = "none";
    T.$("tune-result-body").innerHTML = "";
    // R1：重启轮询——终态停 _pollStop("tune",true) 已清 fn（终态/离页后
    // 再启动，旧链路从此不再刷新、结果面板永远停在旧态的隐性 UX 病）；
    // 与进页注册同款（进页立即拉一次），leave/终态停语义不变。
    _pollRegister("tune", "tune", pollTune, 3000);
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
  kitBtnBusy(T.$("tune-go"), !!st.running, t("tune.start_busy")); // R1：busy 三态收编（disabled 语义不变）
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
    await renderTuneResult(st); // R1：结构化呈现（错误卡/结果卡，裸 JSON 折叠保底）
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

/* ═══ R1（UI 人性化）：终态呈现三件 ═══════════════════════════════════
   renderTuneResult（终态分流：线程异常/失败信封→错误卡，成功→结果卡）、
   tuneErrorCard（信封 errors 解析——HFSS 未连接类内部函数名译成动作指引，
   原文折叠保底）、tuneResultCard（best 参数表+统计+下一步按钮；参数单位
   best-effort 从 /api/recipe 补齐，取不到就空着不阻塞）。全部纯串构建
   （动态数据经 esc/errorText 单点转义），接线只在 renderTuneResult。 */

async function renderTuneResult(st) {
  const box = T.$("tune-result-body");
  if (!box) return;
  if (!st.result) {
    // 线程异常形态（routes/tune.py _TUNE_STATE.error 字符串，result 为空）
    box.innerHTML = tuneErrorCard({ errors: [String(st.error || "")] });
    bindErrorCardActions();
    return;
  }
  const res = st.result;
  if (res.ok === false) {
    box.innerHTML = tuneErrorCard(res); // 失败信封（errors 数组，如 HFSS 未连接）
    bindErrorCardActions(res);
    return;
  }
  const units = await tuneParamUnits(); // best-effort：失败/超时=空表，不阻塞呈现
  box.innerHTML = tuneResultCard(res, units);
  const open = T.$("tune-res-open-run");
  if (open) open.onclick = () => openRun(res.run_id);
  const back = T.$("tune-res-back-recipe");
  if (back) back.onclick = () => showPage("recipe");
}

/* HFSS 未连接类错误的识别（呈现层翻译：内部函数名 connect()/
   open_or_create_project() → 动作指引；匹配失败回通用文案，不误伤）。 */
function _isHfssConnectError(msgs) {
  return msgs.some((m) => /HFSS 未连接|connect\(\)|open_or_create_project/.test(m));
}

function tuneErrorCard(env) {
  const raw = Array.isArray(env.errors) && env.errors.length
    ? env.errors : [env.error || env.reason || ""];
  const msgs = raw.map(String).filter((m) => m.trim());
  const hfss = _isHfssConnectError(msgs);
  const title = hfss ? t("tune.err_hfss_title") : t("tune.err_title");
  const hint = hfss ? t("tune.err_hfss_hint") : t("tune.err_generic_hint");
  const msgHtml = msgs.map(esc).join("<br>"); // 逐条 esc 后再拼接（模板外预构建，裸 API 值不进插值面）
  return `<div class="err-panel" role="alert" style="align-items:flex-start">` +
    `<span aria-hidden="true" style="font-size:20px">⚠️</span>` +
    `<div style="flex:1;min-width:240px">` +
    `<div><span class="badge err">${esc(title)}</span></div>` +
    `<div class="muted" style="margin-top:6px">${msgHtml}</div>` +
    `<div class="muted" style="font-size:12px;margin-top:6px">${esc(hint)}</div>` +
    (hfss ? `<div style="margin-top:8px"><button class="minor" id="tune-err-switch-fake">${esc(t("tune.err_switch_fake"))}</button></div>` : "") +
    `</div></div>` +
    `<details style="margin-top:8px"><summary class="muted">${esc(t("tune.err_raw_label"))}</summary>` +
    `<pre style="white-space:pre-wrap">${esc(JSON.stringify(env, null, 2))}</pre></details>`;
}

/* 错误卡动作接线（幂等：每次渲染后重绑）。「切回 fake」=改选择器+刷新
   预检卡——呈现层状态切换，不自动重发请求。 */
function bindErrorCardActions() {
  const sf = T.$("tune-err-switch-fake");
  if (sf)
    sf.onclick = () => {
      const sel = T.$("tune-adapter");
      if (sel) sel.value = "fake";
      renderPrecheck();
    };
}

/* 参数单位 best-effort：读 /api/recipe 的 params[].unit（配方编辑页同源）。
   任何失败都返回空表——结果卡先出，单位是锦上添花（#105 观测面不阻主路径）。 */
async function tuneParamUnits() {
  try {
    const path = T.$("tune-path") ? T.$("tune-path").value.trim() : "";
    if (!path) return {};
    const d = await apiFetch("/api/recipe?path=" + encodeURIComponent(path));
    if (!d || d.ok === false || !Array.isArray(d.params)) return {};
    const map = {};
    for (const p of d.params) if (p && p.name) map[p.name] = p.unit || "";
    return map;
  } catch { return {}; }
}

function tuneResultCard(res, units) {
  const u = units || {};
  const best = res.best_params && typeof res.best_params === "object"
    ? Object.entries(res.best_params) : null;
  const stats = t("tune.res_stats_tpl", {
    done: res.trials_completed != null ? res.trials_completed : "-",
    pruned: res.trials_pruned != null ? res.trials_pruned : 0,
    secs: res.elapsed_s != null ? fmtNum(res.elapsed_s, 1) : "-",
  });
  let html = `<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">` +
    `<span aria-hidden="true" style="font-size:20px">✅</span>` +
    `<span class="badge ok">${t("tune.res_title")}</span>` +
    `<span class="muted">${esc(stats)}</span></div>`;
  if (best) {
    const rows = best.map(([k, val]) =>
      `<tr><td>${esc(k)}</td><td><b>${esc(typeof val === "number" ? fmtNum(val, 4) : val)}</b></td>` +
      `<td class="muted">${esc(u[k] || "")}</td></tr>`).join("");
    html += `<div style="margin-top:10px"><b>${t("tune.res_best_lead")}</b></div>` +
      `<table><thead><tr><th scope="col">${t("tune.th_params")}</th>` +
      `<th scope="col">${t("tune.th_value")}</th><th scope="col">${t("tune.th_unit")}</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
    if (res.best_cost != null)
      html += `<div class="muted" style="margin-top:6px">${esc(t("tune.res_cost_tpl", { v: fmtNum(res.best_cost, 4) }))}</div>`;
    const bm = res.best_metrics && typeof res.best_metrics === "object"
      ? Object.entries(res.best_metrics) : [];
    if (bm.length)
      html += `<div class="muted" style="margin-top:6px">${esc(t("tune.res_metrics_lead"))} ` +
        bm.map(([k, val]) => esc(`${k}=${typeof val === "number" ? fmtNum(val, 4) : val}`)).join("  ") + `</div>`;
    html += `<div class="muted" style="margin-top:6px;font-size:12px">${esc(t("tune.res_next_hint"))}</div>` +
      `<div class="toolbar" style="gap:8px;margin-top:8px">` +
      (res.run_id ? `<button class="act" id="tune-res-open-run">${t("tune.res_next_runs")}</button>` : "") +
      `<button class="minor" id="tune-res-back-recipe">${t("tune.res_next_recipe")}</button></div>`;
  } else {
    // 多目标等无 best_params 形态：如实给一句话说明（数据在折叠区/run 详情）
    html += `<div class="muted" style="margin-top:8px">${esc(t("tune.res_multi_note"))}</div>` +
      `<div class="toolbar" style="gap:8px;margin-top:8px">` +
      (res.run_id ? `<button class="act" id="tune-res-open-run">${t("tune.res_next_runs")}</button>` : "") +
      `<button class="minor" id="tune-res-back-recipe">${t("tune.res_next_recipe")}</button></div>`;
  }
  html += `<details style="margin-top:8px"><summary class="muted">${esc(t("tune.res_details_label"))}</summary>` +
    `<pre style="white-space:pre-wrap">${esc(JSON.stringify(res, null, 2))}</pre></details>`;
  return html;
}

/* ═══ R1（UI 人性化）：通道预检卡 ═══════════════════════════════════════
   前置条件说在点「启动」之前：选真机通道即出可读卡（HFSS=需先启动并连接
   ANSYS EDT，否则启动立刻失败+一键切回 fake 的出口；openEMS=免费引擎一句
   话说明）。fake=只显示旁注一行。纯呈现层——服务端信封与启动链零改动。 */
function renderPrecheck() {
  const box = T.$("tune-precheck");
  const sel = T.$("tune-adapter");
  if (!box || !sel) return;
  let html = `<div class="muted" style="font-size:12px">${t("tune.adapter_hint")}</div>`;
  if (sel.value === "hfss")
    html += `<div class="err-panel" role="status" style="margin-top:6px;align-items:flex-start">` +
      `<span aria-hidden="true" style="font-size:20px">ℹ️</span>` +
      `<div style="flex:1;min-width:240px">` +
      `<div><span class="badge warn">${t("tune.pre_hfss_title")}</span></div>` +
      `<div class="muted" style="margin-top:4px">${t("tune.pre_hfss_body")}</div>` +
      `<div class="muted" style="font-size:12px;margin-top:4px">${t("tune.pre_hfss_hint")}</div>` +
      `</div></div>`;
  else if (sel.value === "openems")
    html += `<div class="muted" style="font-size:12px;margin-top:6px">ℹ️ ${t("tune.pre_openems_body")}</div>`;
  box.innerHTML = html;
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
