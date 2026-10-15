/* rfauto 优化调参页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   trial 实时监控（SSE 推送 + 3s 轮询回退，两链路经 lifecycle/sse 单源
   托管）。 */

import { plotCardCached } from "./charts.js";
import { T } from "./context.js";
import { esc, help } from "./dom.js";
import { kitEmptyState, kitPanelHead } from "./kit.js";
import { _pollRegister, _pollStop, _pollVisible } from "./polling.js";
import { _SSE, _sseSubscribe, ssePollSuppressed } from "./sse.js";

/* ═══ 优化调参 ═══ */

export async function pageTune() {
  const v = T.$("view-tune");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>adapter</b>：调参用的仿真通道。fake=秒级解析模型（先验证流程）；hfss=真机（慢、耗 license）；openEMS=免费 FDTD。</li>
      <li><b>trials</b>：试验次数——每 trial 仿真一次配方并按 objectives 打分，TPE 采样器会越猜越准。</li>
      <li><b>多保真</b>：先用 fake 粗筛出 Pareto 候选、再对 top-k 用高保真精算（省时数倍）。可信度看 P0 gate（recall≥80%）。</li>
      <li>结果里的 <b>best_params</b> 就是推荐工作点，可回「配方编辑」应用后真机验证。</li>
      <li>调参前确认配方的 objectives 与 optimization.params 范围已定义。</li>`) +
    `<h2 class='page'>优化调参 <small>fake 粗筛 → 高保真精算（多保真）</small></h2>
      <div class='panel'><div class='toolbar'>
        配方: <input id='tune-path' size='36' value='recipes/wilkinson_pd_v1.yaml'>
        adapter: <select id='tune-adapter'><option>fake</option><option>hfss</option><option>openems</option></select>
        trials: <input id='tune-trials' size='4' value='30'>
        sampler: <select id='tune-sampler'><option>tpe</option><option>cmaes</option></select>
        多保真: <input type='checkbox' id='tune-multi'>
        <button class='act' id='tune-go'>启动</button>
        <span id='tune-spin'></span>
      </div><div id='tune-recipe-info' class='muted' style="margin-top:6px"></div></div>
      ${kitPanelHead("结果", "", "id='tune-result' style='display:none'")}<pre id='tune-result-pre'></pre></div>
      <div class='panel'><b class='title'>Trial 实时监控（SSE 进度流可达时推送刷新，否则每 3 秒轮询；收敛曲线 = cost 随 trial 下降）</b>
        <div id='tune-trials-info' class='muted'></div>
        <div id='tune-trials-chart'></div>
        <table id='tune-trials-table'><thead><tr><th scope="col">#</th><th scope="col">cost</th><th scope="col">参数</th><th scope="col">指标</th></tr></thead><tbody></tbody></table></div>`;
  T.$("tune-go").onclick = startTune;
  T.$("tune-path").onchange = showRecipeInfo;
  _pollRegister("tune", "tune", pollTune, 3000); // P2-13：轮询托管（进页即拉/离页守卫/隐藏暂停）
  showRecipeInfo();

  async function showRecipeInfo() {
    const d = await T.api("/api/recipes");
    const r = (d.recipes || []).find((x) => x.path === T.$("tune-path").value.trim());
    T.$("tune-recipe-info").innerHTML = r
      ? `已选配方：<b>${esc(r.model)}</b>，${esc(r.n_params)} 个参数，${esc(r.n_objectives)} 个目标，频段 ${esc(JSON.stringify(r.freq_range))}。要素含义见「配方编辑」页底部说明。`
      : "配方路径未在目录中找到，加载后仍可运行。";
  }
  async function startTune() {
    const r = await T.api("/api/tune/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: T.$("tune-path").value.trim(),
                             adapter: T.$("tune-adapter").value,
                             max_trials: parseInt(T.$("tune-trials").value) || 30,
                             sampler: T.$("tune-sampler").value }),
    });
    if (!r.ok) return T.msg(r.error, false);
    T.msg("调参已启动，状态轮询中...", true);
  }
  async function pollTune() {
    if (!_pollVisible("tune")) return; // P2-13：当前页+可见性双守卫（跳过 fetch，定时器保留）
    if (ssePollSuppressed(_SSE.tune)) return; // A6-A：SSE 流活跃——定时器保留、回调跳过降负载（断流自然回退轮询）
    await tuneRefresh();
  }

  /* A6-A：轮询回调与 SSE 推送共用的拉取+渲染体（幂等整页刷新）——SSE
     kick（含 end/error 帧的末次刷新）也走这里，终态停与结果面板逻辑同款。 */
  async function tuneRefresh() {
    const st = await T.api("/api/tune/status");
    T.$("tune-spin").innerHTML = st.running ? "<span class='spin'></span> 运行中" : "";
    T.$("tune-go").disabled = !!st.running;
    if (!st.running && (st.result || st.error)) {
      _pollStop("tune", true); // 终态停：清 fn，恢复可见不得复活已完成的轮询
      T.$("tune-result").style.display = "";
      if (st.error) T.$("tune-result-pre").textContent = "错误: " + st.error;
      else T.$("tune-result-pre").textContent = JSON.stringify(st.result, null, 2);
    }
    renderTrials(st);
  }

  // trial 级实时监控：读 runs/<run_id>/trials/*.json（服务端聚合）
  async function renderTrials(st) {
    const info = T.$("tune-trials-info");
    if (!info) return;
    const d = await T.api("/api/tune/trials");
    const trials = d.trials || [];
    if (d.run_id) _sseSubscribe("tune", d.run_id, tuneRefresh, "tune"); // A6-A：有 run 即订阅进度流（幂等；trial 推送期轮询让位）
    if (!trials.length) {
      // A8-A（R6 审计 P-3）：空态三件式——动作钮转触既有「启动调参」（tune-go）
      info.innerHTML = kitEmptyState("暂无 trial 数据（启动调参后这里实时出点）",
        { icon: "⚙", label: "启动调参", id: "tune-empty-go" });
      const teg = T.$("tune-empty-go");
      const tgo = T.$("tune-go");
      if (teg && tgo) teg.onclick = () => tgo.click();
      return;
    }
    info.innerHTML = `run <b>${esc(d.run_id)}</b> · 已完成 ${trials.length} trials`
      + (st?.running ? " · <span class='spin'></span> 进行中" : "");
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
      ariaLabel: "图表：cost，纵轴 cost，横轴 trial（含 best-so-far 阶梯）",
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
}
