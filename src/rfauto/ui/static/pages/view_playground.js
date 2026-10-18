/* rfauto 代理 Playground 页（aurora_d UI-R2 自 pages.js 拆出，逐字节
   搬移）：滑条 → 代理实时预测（诚实呈现）+ 单轴探索（mean±σ 带）。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { kitTable, kitVerdictBadge } from "./kit.js";

/* ═══ 代理 Playground（E3/WP0.4：滑条 → 代理实时预测，诚实呈现）═══ */
export async function pagePlayground() {
  const v = T.$("view-playground");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>选一个已校准 run（有 calibration 产物），拖动参数滑条实时看代理预测指标。</li>
      <li><b>诚实呈现</b>：预测来自校准样本拟合的代理模型，<b>非真值</b>——LOOCV ρ/样本量与最近样本真值对照一并列出，精算以 openEMS/HFSS 求解为准。</li>
      <li>缺省值=参数界中点；越界滑条值会被裁剪到边界并在状态行提示。</li>
      <li>下方探索器沿单轴做参数扫描切片，画后验 mean 曲线并叠加 <b>±1σ 方差带</b>（面积阴影；仅 smt 族代理有原生逐点 σ，其余如实只画 mean）。</li>`) +
    `<h2 class='page'>代理 Playground</h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b><select id='pg-run' style='max-width:460px'></select>
         <span id='pg-quality'></span></div>
       <div id='pg-sliders'></div>
       <div id='pg-note' class='muted' style='margin-top:var(--space-2)'></div>
     </div>
     <div class='panel' style='margin-top:14px'><b class='title'>代理预测 vs 最近样本真值</b>
       <div id='pg-result' class='muted'>选择 run 后自动预测</div></div>
     <div class='panel' style='margin-top:14px'><b class='title'>参数扫描探索（explore：后验 mean±std）</b>
       <div class='toolbar'>扫参轴 <select id='pg-ex-axis'></select>
         点数 <select id='pg-ex-n'><option value='11'>11</option><option value='21'>21</option><option value='41' selected>41</option></select>
         指标 <select id='pg-ex-metric'></select>
         <span id='pg-ex-status' class='muted'></span></div>
       <div id='pg-ex-chart'></div>
       <div id='pg-ex-note' class='muted' style='margin-top:var(--space-2)'></div></div>`;
  const d = await T.api("/api/playground/runs");
  const runs = d.runs || [];
  const sel = T.$("pg-run");
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.best_surrogate || "?")} · ρ=${r.rho == null ? "-" : (+r.rho).toFixed(3)} · ${esc(r.verdict || "-")}）</option>`).join("");
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
    const r = await T.api("/api/playground/explore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: sel.value,
        params: currentParams(),
        sweep: { axis: T.$("pg-ex-axis").value, n: +T.$("pg-ex-n").value },
      }),
    });
    const st = T.$("pg-ex-status");
    if (!r.ok) {
      st.innerHTML = `<span style='color:var(--err)'>✗ ${esc(r.error)}</span>`;
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
    // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径，含 band 系列）
    T.plotCard(T.$("pg-ex-chart"), {
      series,
      xlabel: axisName, ylabel: key, xvalue: true, height: "300px",
      exportName: "explore-sweep", exportCsv: false,
    });
    st.textContent = `engine=${r.engine} · ${r.has_variance ? "mean±1σ" : "mean（无原生 σ）"}`
      + ` · fixed=${JSON.stringify(r.sweep.fixed)}`;
    T.$("pg-ex-note").textContent = `${r.variance_note}；${r.honest_note}`;
  };
  for (const id of ["pg-ex-axis", "pg-ex-n", "pg-ex-metric"])
    T.$(id).onchange = runExplore;
  const predict = async (params) => {
    const r = await T.api("/api/playground/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: sel.value, params }),
    });
    const box = T.$("pg-result");
    if (!r.ok) {
      box.innerHTML = `<span style='color:var(--err)'>✗ ${esc(r.error)}</span>`;
      return;
    }
    const q = r.quality;
    T.$("pg-quality").innerHTML =
      (q.rho == null ? "" :
        kitVerdictBadge(q.verdict, // A7-A ui-kit：二元判定单源（PASS→ok，其余 FAIL/err）
          q.verdict === "PASS" ? `ρ=${(+q.rho).toFixed(3)} PASS` : `ρ=${(+q.rho).toFixed(3)} FAIL`)) +
      ` <span class='muted'>n=${esc(q.n_samples ?? "-")} · ${esc(r.kind)}</span>` +
      (r.clamped.length ? T.badge(`越界裁剪: ${r.clamped.join(", ")}`, "muted") : "");
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
      columns: ["指标", "代理预测",
        "最近样本真值（归一化距离 " + r.nearest_sample.normalized_distance + "）"],
      rowsHtml: rows, empty: "",
    });
  };
  sel.onchange = () => { lastRun = null; predict({}); };
  if (runs.length) await predict({});
  else T.$("pg-result").textContent = "暂无有校准产物的 run（先跑校准战役）";
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 playgroundCtx ════════
   refresh=run 清单+缺省预测重拉（pagePlayground 幂等——壳判 innerHTML 已在
   即跳过；滑条随 lastRun 闭包重建=与重进同语义）。无轮询面，leave 不需要。 */
export const playgroundCtx = {
  refresh: () => pagePlayground(),
};
