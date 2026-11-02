/* rfauto 代理 Playground 页（aurora_d UI-R2 自 pages.js 拆出，逐字节
   搬移）：滑条 → 代理实时预测（诚实呈现）+ 单轴探索（mean±σ 带）。
   aurora_n wave_ui_pg 增量：探索器对比模式——第二 run 选择器（pg-ex-run2，
   缺省空=单键模式既有路径逐位保留）+ 双代理预测曲线叠加（A 蓝/B 橙，
   曲线名带各键；纯前端，服务端零语义变化）。
   i18n（发布前软编码批 S2 全清）：help 块分段 t()、标题/面板头/工具栏
   标签/表头/空态全迁词表（playground.* 键域，zh 与旧字面逐字节同、en
   新增）；run 清单选项/滑条标签/曲线名为 API 数据照旧 esc/直拼——数据
   非文案不迁；归一化距离为数值可作 t() params（agent stats 前例）。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { T } from "./context.js";
import { esc, escAttr, errorText, help } from "./dom.js";
// i18n（发布前软编码批 S2）：壳静态标签 data-i18n+首扫；动态容器（预测
// 结果/探索状态）文案 t() 渲染期烘焙——pg-result 随数据重建不挂 data-i18n。
import { t, applyI18nRoot } from "./i18n.js";
import { kitErrorPanel, kitTable, kitVerdictBadge } from "./kit.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 3 点）——
// 数据面（run 清单）接 viewSignal("playground") 切页收束 + aborted 短路；动作
// 面（预测/探索 POST——滑条与探索钮触发）保持无 signal（用户动作不被切页
// 取消）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ 代理 Playground（E3/WP0.4：滑条 → 代理实时预测，诚实呈现）═══ */
export async function pagePlayground() {
  const v = T.$("view-playground");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("playground.help_1")}</li>
      <li><b>${t("playground.help_2_core")}</b>${t("playground.help_2_mid")}<b>${t("playground.help_2_core2")}</b>${t("playground.help_2_tail")}</li>
      <li>${t("playground.help_3")}</li>
      <li>${t("playground.help_4_lead")}<b>${t("playground.help_4_core")}</b>${t("playground.help_4_tail")}</li>
      <li>${t("playground.help_5")}</li>`) +
    `<h2 class='page'><span data-i18n='playground.title'>${t("playground.title")}</span></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b><select id='pg-run' style='max-width:460px'></select>
         <span id='pg-quality'></span></div>
       <div id='pg-sliders'></div>
       <div id='pg-note' class='muted' style='margin-top:var(--space-2)'></div>
     </div>
     <div class='panel' style='margin-top:14px'><b class='title' data-i18n='playground.compare_title'>${t("playground.compare_title")}</b>
       <div id='pg-result' class='muted'>${t("playground.auto_predict")}</div></div>
     <div class='panel' style='margin-top:14px'><b class='title' data-i18n='playground.explore_title'>${t("playground.explore_title")}</b>
       <div class='toolbar'><span data-i18n='playground.sweep_axis'>${t("playground.sweep_axis")}</span> <select id='pg-ex-axis'></select>
         <span data-i18n='playground.n_points'>${t("playground.n_points")}</span> <select id='pg-ex-n'><option value='11'>11</option><option value='21'>21</option><option value='41' selected>41</option></select>
         <span data-i18n='playground.metric'>${t("playground.metric")}</span> <select id='pg-ex-metric'></select>
         <span data-i18n='playground.compare_b'>${t("playground.compare_b")}</span> <select id='pg-ex-run2'></select>
         <span id='pg-ex-status' class='muted'></span></div>
       <div id='pg-ex-chart'></div>
       <div id='pg-ex-note' class='muted' style='margin-top:var(--space-2)'></div></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（幂等，动态容器走 t() 烘焙）
  const d = await apiFetch("/api/playground/runs",
    { signal: viewSignal("playground") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runs = d.runs || [];
  const sel = T.$("pg-run");
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.best_surrogate || "?")} · ρ=${r.rho == null ? "-" : (+r.rho).toFixed(3)} · ${esc(r.verdict || "-")}）</option>`).join("");
  // 对比模式 B 选择器（aurora_n wave_ui_pg）：与主 run 清单同源；空选项=
  // 单键模式（缺省，既有路径零回归）。选项名带各 run 校准最佳代理键——
  // A/B 两键是什么在下拉里即可读（run/代理键=API 数据照旧 esc 不迁）。
  T.$("pg-ex-run2").innerHTML =
    `<option value=''>${esc(t("playground.compare_b_none"))}</option>` +
    runs.map((r) =>
      `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.best_surrogate || "?")}）</option>`).join("");
  let debounce = null;
  let lastRun = null;
  const key = (name) => name.replace(/\W/g, "_");
  const currentParams = () => {
    const out = {};
    for (const input of T.$("pg-sliders").querySelectorAll("input[type=range]"))
      out[input.dataset.param] = +input.value;
    return out;
  };
  /* ── 探索器（DP-16 U3）：单轴参数扫描切片 → 后验 mean±std 曲线 ── */
  let exDebounce = null;
  let exReady = false;
  const scheduleExplore = () => {
    clearTimeout(exDebounce);
    exDebounce = setTimeout(runExplore, 250);
  };
  const ensureExploreControls = (bounds, metrics) => {
    const ax = T.$("pg-ex-axis");
    if (exReady && ax.dataset.run === sel.value) return;
    ax.dataset.run = sel.value;
    ax.innerHTML = Object.keys(bounds).map(
      (k) => `<option value='${escAttr(k)}'>${esc(k)}</option>`).join("");
    T.$("pg-ex-metric").innerHTML = metrics.map(
      (k) => `<option value='${escAttr(k)}'>${esc(k)}</option>`).join("");
    exReady = metrics.length > 0;
  };
  const runExplore = async () => {
    if (!sel.value || !exReady) return;
    const r = await apiFetch("/api/playground/explore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: sel.value,
        params: currentParams(),
        sweep: { axis: T.$("pg-ex-axis").value, n: +T.$("pg-ex-n").value },
      }),
      timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：逐点代理评估分钟级
    });
    const st = T.$("pg-ex-status");
    if (!r.ok) {
      // W14-S2 错误呈现归一（R2 Top10 #4）：内联 ✗ span → kitErrorPanel 单源
      // （文案走 errorText 信封回退链 errors→error→reason，原裸读 r.error 在
      // errors 列表信封下会渲染 "undefined"——dom.js errorText 头注实证）。
      st.innerHTML = kitErrorPanel(errorText(r));
      return;
    }
    const metrics = Object.keys(r.curves);
    const key = metrics.includes(T.$("pg-ex-metric").value)
      ? T.$("pg-ex-metric").value : metrics[0];
    const cur = r.curves[key];
    const axisName = r.sweep.axes[0];
    const xs = r.sweep.axes_values[axisName].map((v) => +(+v).toFixed(4));
    const series = [{ name: `${key} mean`, x: xs, y: cur.mean,
    color: themePick(bodyIsLight(), THEME_COLORS.seriesBlue) }];
    if (cur.std)
      /* 方差带（B3 批）：GP ±1σ 区间画成面积带（app.js drawEChart band 类型），
         替代旧的两条 ±1σ 虚线——带形态更可读且不占图例双行 */
      series.push(
        { name: `${key} ±1σ`, type: "band", x: xs,
        color: themePick(bodyIsLight(), THEME_COLORS.seriesBlue),
          lower: cur.mean.map((m, i) => m - cur.std[i]),
          upper: cur.mean.map((m, i) => m + cur.std[i]) });
    // ── 对比模式（aurora_n wave_ui_pg，纯前端增强：服务端零语义变化）──
    // 第二 run 选择器非空且 ≠ 当前 run 时，同滑条/同扫参轴对 B run 的校准
    // 最佳代理再拉一次 explore，双曲线叠加（A=蓝既有、B=橙 seriesOrange），
    // 曲线名带各键（A/B 两键图例可读——色分+图例=差异区可读）。B==A 同 run
    // 不对比（曲线恒同无义）；B 拉取失败/轴不在 B bounds（服务 ok=false）/
    // 指标缺失=状态行如实记因，主曲线不受阻（#105 家法：观测增强不拦主
    // 路径）。单键模式（B=空，缺省）不走此分支——既有路径逐位保留。
    let cmpNote = "";
    const runB = T.$("pg-ex-run2").value;
    if (runB && runB !== sel.value) {
      const rb = await apiFetch("/api/playground/explore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runB,
          params: currentParams(),
          sweep: { axis: T.$("pg-ex-axis").value, n: +T.$("pg-ex-n").value },
        }),
        timeoutMs: 0, // 长跑豁免（P9-11）：与 A 探索请求同口径
      });
      const cmp = compareExploreSeries(r, rb, key, axisName, bodyIsLight());
      if (cmp && cmp.seriesB) {
        series[0].name = cmp.nameA;
        series.push(cmp.seriesB);
        cmpNote = `${rb.kind}=${rb.has_variance ? "mean±1σ"
          : t("playground.no_native_std")}`;
      } else if (cmp) {
        cmpNote = t("playground.compare_b_no_metric_tpl", { k: key });
      } else {
        cmpNote = errorText(rb);
      }
    }
    // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径，含 band 系列）
    // W3-S9：数值读数类开十字线（xvalue 值轴 trigger=item，与 cred 卡同款组合）
    T.plotCard(T.$("pg-ex-chart"), {
      series,
      xlabel: axisName, ylabel: key, xvalue: true, crosshair: true, height: "300px",
      exportName: "explore-sweep", exportCsv: false,
    });
    st.textContent = `engine=${r.engine} · ${r.has_variance ? "mean±1σ" : t("playground.no_native_std")}`
      + ` · fixed=${JSON.stringify(r.sweep.fixed)}`
      + (cmpNote ? ` · B: ${cmpNote}` : "");
    T.$("pg-ex-note").textContent = `${r.variance_note}；${r.honest_note}`;
  };
  for (const id of ["pg-ex-axis", "pg-ex-n", "pg-ex-metric", "pg-ex-run2"])
    T.$(id).onchange = runExplore;
  const predict = async (params) => {
    const r = await apiFetch("/api/playground/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: sel.value, params }),
    });
    const box = T.$("pg-result");
    if (!r.ok) {
      // W14-S2 错误呈现归一（R2 Top10 #4）：内联 ✗ span → kitErrorPanel 单源
      //（同上 errorText 信封回退链；动作失败无重试钮，gallery 闭式失败点同款）。
      box.innerHTML = kitErrorPanel(errorText(r));
      return;
    }
    const q = r.quality;
    T.$("pg-quality").innerHTML =
      (q.rho == null ? "" :
        kitVerdictBadge(q.verdict, // A7-A ui-kit：二元判定单源（PASS→ok，其余 FAIL/err）
          q.verdict === "PASS" ? `ρ=${(+q.rho).toFixed(3)} PASS` : `ρ=${(+q.rho).toFixed(3)} FAIL`)) +
      ` <span class='muted'>n=${esc(q.n_samples ?? "-")} · ${esc(r.kind)}</span>` +
      (r.clamped.length ? T.badge(t("playground.clamped_lead") + r.clamped.join(", "), "muted") : "");
    T.$("pg-note").textContent = r.honest_note;
    if (lastRun !== sel.value) {
      lastRun = sel.value;
      ensureExploreControls(r.bounds, Object.keys(r.predicted));
      T.$("pg-sliders").innerHTML = Object.entries(r.bounds).map(([name, b]) =>
        `<label class='muted' style='display:block;margin:10px 0 2px'>${esc(name)}
          <span id='pg-val-${key(name)}'></span>
          <input type='range' data-param='${escAttr(name)}' id='pg-s-${key(name)}'
            min='${escAttr(b[0])}' max='${escAttr(b[1])}' step='${((b[1] - b[0]) / 100).toFixed(5)}'
            value='${escAttr(r.params[name])}' style='width:100%'></label>`).join("");
      for (const input of T.$("pg-sliders").querySelectorAll("input[type=range]")) {
        const vk = "pg-val-" + key(input.dataset.param);
        T.$(vk).textContent = (+input.value).toFixed(3);
        input.oninput = () => {
          T.$(vk).textContent = (+input.value).toFixed(3);
          clearTimeout(debounce);
          debounce = setTimeout(() => predict(currentParams()), 250);
          scheduleExplore();
        };
      }
    }
    const near = r.nearest_sample.metrics || {};
    const rows = Object.entries(r.predicted).map(([k, val]) =>
      `<tr><td class='muted'>${esc(k)}</td><td><b>${esc(val)}</b></td>
       <td class='muted'>${near[k] == null ? "-" : (+near[k]).toFixed(4)}</td></tr>`).join("");
    // A7-A ui-kit 试点：表壳单源（kitTable）。动态列名改串接进列头文本
    //（原裸插值形态退场，XSS 豁免清单同笔清理）——kit 内 esc 对数值域恒等
    //（逐字节等价），异常串从裸插值升级为转义；empty:"" 保持空 tbody 等价。
    box.innerHTML = kitTable({
      columns: [t("playground.th_metric"), t("playground.th_pred"),
        t("playground.th_nearest_tpl", { d: r.nearest_sample.normalized_distance })],
      rowsHtml: rows, empty: "",
    });
  };
  sel.onchange = () => { lastRun = null; predict({}); };
  if (runs.length) await predict({});
  else T.$("pg-result").textContent = t("playground.no_runs");
}

/* ═══ 对比模式系列组装（aurora_n wave_ui_pg 导出纯函数，node 行为钉面）═══
   输入 A/B 两份 explore 信封 + 指标键 + 扫参轴 + 主题亮暗 → B 叠加系列
   （橙 seriesOrange，曲线名带 B 代理键；A 名改带 A 键由调用方写回 series[0]）。
   诚实跳过面：B 信封不 ok/畸形/缺同指标 → null / {skip:true}——调用方状态
   行如实记因，不硬造第二曲线（#122 不凑绿纪律的前端同构）。本函数是纯
   组装器不触 DOM/网络；单键模式不消费（既有路径逐位保留）。 */
export function compareExploreSeries(rA, rb, metricKey, axisName, light) {
  if (!rA || !rA.kind || !rb || rb.ok !== true || !rb.kind
    || !rb.curves || typeof rb.curves !== "object")
    return null;
  if (!Object.prototype.hasOwnProperty.call(rb.curves, metricKey))
    return { skip: true };
  const vals = (rb.sweep && rb.sweep.axes_values
    && rb.sweep.axes_values[axisName]) || null;
  const mean = rb.curves[metricKey] && rb.curves[metricKey].mean;
  if (!Array.isArray(vals) || !Array.isArray(mean)
    || vals.length !== mean.length)
    return null;
  return {
    nameA: `${metricKey} mean·${rA.kind}`,
    seriesB: {
      name: `${metricKey} mean·${rb.kind}`,
      x: vals.map((v) => +(+v).toFixed(4)),
      y: mean,
      color: themePick(!!light, THEME_COLORS.seriesOrange),
    },
  };
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 playgroundCtx ════════
   refresh=run 清单+缺省预测重拉（pagePlayground 幂等——壳判 innerHTML 已在
   即跳过；滑条随 lastRun 闭包重建=与重进同语义）。无轮询面，leave 不需要。 */
export const playgroundCtx = {
  refresh: () => pagePlayground(),
};
