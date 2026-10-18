/* rfauto 配方编辑页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   配方目录 + 参数表 + setup/optimization 表单化 + 3D 预览。 */

import { releaseWebGLIn } from "./charts.js";
import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { bindClickRows, kitClickRowAttrs } from "./kit.js";
import { openRun } from "./router.js";

/* ═══ 配方编辑（含配方目录 + 字段说明）═══ */
let currentRecipe = null;
/* UI-R11（A6 P2-7 可测试性半边，W8B P2-4 清偿）：动态表单控件按 pg-s-*
   惯例生成 id（key() 把参数名消毒为 \w 形态，querySelector 稳健；
   data-* 消费位一律不动，id 是纯增量挂钩）。 */
const key = (s) => String(s).replace(/\W/g, "_");

export async function pageRecipe() {
  const v = T.$("view-recipe");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>配方目录</b>：recipes/ 下全部配方，点选加载。每个配方 = 一次仿真的完整定义（模型+参数+目标+优化设置）。工作副本（runs/recipe_workcopy/）单独分组显示并标注「工作副本」——保存对原件的改动会重定向到工作副本（原件受保护），人工审阅后经审批链（rfauto inbox）入库。</li>
      <li><b>参数表</b>：改值即时刷新 3D 预览；「优化范围」是调参时允许搜索的区间。</li>
      <li><b>保存并运行</b>：单次仿真——fake 秒级演示 / openEMS 真跑 / HFSS 真机。</li>
      <li>各字段含义见页面底部「配方要素说明」。</li>`) +
    `<h2 class='page'>配方编辑</h2>
      <div class='grid2'>
        <div class='panel'><b class='title'>配方目录（点选加载）</b><div id='recipe-cat' class='muted'>加载中...</div></div>
        <div class='panel'><div class='toolbar' style="align-items:flex-start;flex-direction:column">路径:
          <input id='recipe-path' style='width:100%' placeholder='recipes/wilkinson_pd_v1.yaml'>
          <button class='minor' id='recipe-load'>加载</button>
          <span class='muted'>模型: <span id='recipe-model'>-</span></span></div>
        </div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title'>参数（可改值；保存后生效）</b><table id='params-table'><thead>
          <tr><th scope="col">名称</th><th scope="col">值</th><th scope="col">单位</th><th scope="col">优化范围</th></tr></thead><tbody></tbody></table>
          <p class='toolbar'><button class='act' id='recipe-save'>保存配方</button>
          <button class='act' id='recipe-run'>运行一次</button>
          <select id='run-adapter'><option value='fake'>fake（秒级演示）</option><option value='openems'>openEMS（FDTD 真跑）</option><option value='hfss'>HFSS（真机）</option></select></p></div>
        <div class='panel'><b class='title'>3D 预览（随表单值实时渲染）</b><div id='recipe-3d'></div></div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title'>扫频 / 仿真设置 (setup) — 表单化</b>
          <div id='setup-form' class='toolbar' style='flex-wrap:wrap;gap:var(--space-2)'></div>
          <details class='help' style='margin-top:var(--space-2)'><summary>高级：完整 setup JSON（表单改不到的字段在这改）</summary>
          <pre id='setup-pre' contenteditable='true' spellcheck='false'></pre></details></div>
        <div class='panel'><b class='title'>优化设置 (optimization + objectives)</b>
          <div id='opt-form'></div>
          <details class='help' style='margin-top:var(--space-2)'><summary>高级：objectives JSON（目标判定，表单改不到）</summary>
          <pre id='opt-pre' contenteditable='true' spellcheck='false'></pre></details></div>
      </div>
      <div class='panel'><b class='title'>配方要素说明</b><div id='recipe-help' class='muted'></div></div>`;
  T.$("recipe-load").onclick = loadRecipe;
  T.$("recipe-save").onclick = () => saveRecipe(false);
  T.$("recipe-run").onclick = () => saveRecipe(true);
  loadCatalog();

  async function loadCatalog() {
    const d = await T.api("/api/recipes");
    const el = T.$("recipe-cat");
    const orig = d.recipes || [], work = d.workcopies || [];
    // UI-R4：目录行键盘可达（div 行 role=button 缺省；aria-label 行动作——
    // path 经 kit escAttr 出口转义）
    const row = (r, isWorkcopy) =>
      `<div class="clickable" style="padding:5px 8px;border-radius:var(--radius-xs)" data-p="${escAttr(r.path)}" ${kitClickRowAttrs({ label: "加载配方：" + (r.path || "") })}>
        <b>${esc(r.path.split("/").pop())}</b> ${isWorkcopy ? T.badge("工作副本", "warn") + " " : ""}<span class="muted">${esc(r.model)}</span><br>
        <span class="muted" style="font-size:11.5px">${esc(r.n_params ?? "?")} 参数 · ${esc(r.n_objectives ?? "?")} 目标 · 频段 ${esc(JSON.stringify(r.freq_range))}</span></div>`;
    // C22 分组：recipes/ 原件在上；工作副本（runs/recipe_workcopy/）单独分组，
    // 标注「工作副本」并给人工审阅入库提示（rfauto inbox 审批链，前端只渲染）。
    el.innerHTML =
      `<div style="margin-bottom:var(--space-1)"><b>原件（recipes/）</b> <span class="muted" style="font-size:11.5px">${orig.length} 个</span></div>` +
      orig.map((r) => row(r, false)).join("") +
      (work.length ?
        `<div style="margin:10px 0 4px"><b>工作副本（runs/recipe_workcopy/）</b> <span class="muted" style="font-size:11.5px">${work.length} 个</span></div>` +
        `<div class="muted" style="font-size:11.5px;margin:0 0 4px">人工审阅后入库：与原件 diff 确认改动 → 经审批链（<b>rfauto inbox</b> 审批收件箱，propose→approve→apply 三层 Gate）或显式写回原件后 git commit 留痕。</div>` +
        work.map((r) => row(r, true)).join("")
        : "");
    el.querySelectorAll("[data-p]").forEach((row) => {
      row.onmouseenter = () => { row.style.background = "var(--panel2)"; };
      row.onmouseleave = () => { row.style.background = ""; };
    });
    // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源）
    bindClickRows(el, (row) => { T.$("recipe-path").value = row.dataset.p; loadRecipe(); }, "[data-p]");
    T.$("recipe-help").innerHTML = Object.entries(d.help || {}).map(([k, txt]) =>
      `<div style="margin-bottom:6px"><b style="color:var(--fg)">${esc(k)}</b> — ${esc(txt)}</div>`).join("");
  }

  async function loadRecipe() {
    const val = await T.api("/api/recipe?path=" + encodeURIComponent(T.$("recipe-path").value.trim()));
    if (!val.ok) return T.msg(val.errors.join("; "), false);
    currentRecipe = val;
    // C22：工作副本视图标注（service 端 is_workcopy/review_hint，前端只渲染）
    T.$("recipe-model").textContent =
      `${val.model}（模板: ${val.template_hint || "无"}）` + (val.is_workcopy ? " · 工作副本" : "");
    T.$("recipe-model").title = val.is_workcopy ? (val.review_hint || "") : "";
    const tb = T.$("params-table").tBodies[0];
    tb.innerHTML = "";
    for (const p of val.params) {
      const bounds = p.bounds ? `[${p.bounds.join(", ")}]`
        : (val.optimization.params[p.name] ? `[${val.optimization.params[p.name].low}, ${val.optimization.params[p.name].high}]` : "-");
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(p.name)}</td><td><input id="rp-param-${key(p.name)}" data-param="${escAttr(p.name)}" value="${escAttr(p.value ?? "")}" size="10" aria-label="参数 ${escAttr(p.name)} 的值"></td><td>${esc(p.unit || "")}</td><td class="muted">${esc(bounds)}</td>`;
      tr.querySelector("input").oninput = renderRecipe3D;
      tb.appendChild(tr);
    }
    T.$("setup-pre").textContent = JSON.stringify(val.setup, null, 2);
    T.$("opt-pre").textContent = JSON.stringify({ objectives: val.objectives, optimization: val.optimization }, null, 2);
    renderSetupForm(val.setup);
    renderOptForm(val.optimization);
    renderRecipe3D();
  }

  /* 扫参表单化：表单是主输入，写回 JSON 编辑框（保存仍以 JSON 为准，链路不变） */
  function renderSetupForm(setup) {
    const fr = Array.isArray(setup.freq_range_ghz) ? setup.freq_range_ghz : ["", ""];
    const fields = [
      ["solver", "求解器", setup.solver ?? "", "text"],
      ["f0", "扫频起 (GHz)", fr[0] ?? "", "number"],
      ["f1", "扫频止 (GHz)", fr[1] ?? "", "number"],
      ["points", "频点数", setup.points ?? "", "number"],
      ["convergence_delta", "收敛 Δ", setup.convergence_delta ?? "", "number"],
      ["radiation_box", "辐射边界", setup.radiation_box ?? "", "text"],
    ];
    const form = T.$("setup-form");
    form.innerHTML = fields.map(([k, label, v, t]) =>
      `<label>${label}: <input id="rp-setup-${k}" data-setup="${k}" type="${t}" value="${escAttr(v)}" size="9" step="any"></label>`).join("");
    form.oninput = syncSetupForm;
  }
  function syncSetupForm() {
    let s;
    try { s = JSON.parse(T.$("setup-pre").textContent) || {}; }
    catch { return; } // JSON 被手改坏了就不覆盖，保存时会报错提示
    const read = (k) => {
      const el = form.querySelector(`input[data-setup="${k}"]`);
      if (!el) return undefined;
      const raw = el.value.trim();
      if (el.type === "number") { const n = Number(raw); return raw === "" ? undefined : (isNaN(n) ? raw : n); }
      return raw === "" ? undefined : raw;
    };
    const form = T.$("setup-form");
    const assign = (obj, k, v) => { if (v !== undefined) obj[k] = v; };
    assign(s, "solver", read("solver"));
    assign(s, "radiation_box", read("radiation_box"));
    assign(s, "points", read("points"));
    assign(s, "convergence_delta", read("convergence_delta"));
    const f0 = read("f0"), f1 = read("f1");
    if (f0 !== undefined || f1 !== undefined) {
      const old = Array.isArray(s.freq_range_ghz) ? s.freq_range_ghz : [undefined, undefined];
      s.freq_range_ghz = [f0 ?? old[0], f1 ?? old[1]];
    }
    T.$("setup-pre").textContent = JSON.stringify(s, null, 2);
  }
  function renderOptForm(opt) {
    const names = Object.keys(opt.params || {});
    const form = T.$("opt-form");
    if (!names.length) { form.innerHTML = "<span class='muted'>配方未定义 optimization.params（搜索空间）</span>"; return; }
    form.innerHTML = `<table><thead><tr><th scope="col">调参变量</th><th scope="col">low</th><th scope="col">high</th></tr></thead><tbody>` +
      names.map((n) => {
        const p = opt.params[n] || {};
        return `<tr><td><b>${esc(n)}</b></td>
          <td><input id="rp-opt-${key(n)}-low" class="opt-b" data-param="${escAttr(n)}" data-k="low" value="${escAttr(p.low ?? "")}" size="9" type="number" step="any" aria-label="${escAttr(n)} 搜索下界 low"></td>
          <td><input id="rp-opt-${key(n)}-high" class="opt-b" data-param="${escAttr(n)}" data-k="high" value="${escAttr(p.high ?? "")}" size="9" type="number" step="any" aria-label="${escAttr(n)} 搜索上界 high"></td></tr>`;
      }).join("") + "</tbody></table>" +
      `<div class="muted" style="margin-top:var(--space-1);font-size:11.5px">调整搜索空间（low/high）；目标 objectives 在右侧「高级」折叠框里。</div>`;
    form.oninput = syncOptForm;
  }
  function syncOptForm() {
    let d;
    try { d = JSON.parse(T.$("opt-pre").textContent); }
    catch { return; }
    d.optimization = d.optimization || {};
    d.optimization.params = d.optimization.params || {};
    document.querySelectorAll("#opt-form input.opt-b").forEach((el) => {
      const p = d.optimization.params[el.dataset.param];
      if (!p) return;
      const n = Number(el.value);
      if (el.value.trim() !== "" && !isNaN(n)) p[el.dataset.k] = n;
    });
    T.$("opt-pre").textContent = JSON.stringify(d, null, 2);
  }

  /* P0-4：参数 oninput 每键一渲染 → 250ms 防抖（与 playground 同款）收敛
     渲染频次；绘制前经 releaseWebGLIn 弃置上一代 WebGL 上下文（调用侧
     防御；根治需 app.js drawBoxes 返回 renderer 句柄+dispose——接口诉求
     见 releaseWebGLIn 注释，合流转 W2-C）。 */
  let r3dDebounce = null;
  function renderRecipe3D() {
    if (!currentRecipe) return;
    clearTimeout(r3dDebounce);
    r3dDebounce = setTimeout(r3dDraw, 250);
  }
  async function r3dDraw() {
    const params = {};
    document.querySelectorAll("#params-table input[data-param]").forEach((el) => {
      params[el.dataset.param] = Number(el.value) || 0;
    });
    const r = await T.api("/api/model3d", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: currentRecipe.template_hint, params }),
    });
    releaseWebGLIn(T.$("recipe-3d")); // P0-4 防御式：弃置上一代 WebGL 上下文
    T.drawBoxes(T.$("recipe-3d"), r);
  }

  async function saveRecipe(andRun) {
    if (!currentRecipe) return T.msg("先加载配方", false);
    const updates = { params: {} };
    document.querySelectorAll("#params-table input[data-param]").forEach((el) => {
      const raw = el.value.trim();
      updates.params[el.dataset.param] = isNaN(Number(raw)) || raw === "" ? raw : Number(raw);
    });
    try { updates.setup = JSON.parse(T.$("setup-pre").textContent); }
    catch { return T.msg("setup 不是合法 JSON", false); }
    try {
      const opt = JSON.parse(T.$("opt-pre").textContent);
      updates.objectives = opt.objectives; updates.optimization = opt.optimization;
    } catch { return T.msg("optimization/objectives 不是合法 JSON", false); }
    const r = await T.api("/api/recipe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentRecipe.recipe_path, updates }),
    });
    if (!r.ok) return T.msg("保存被拒: " + r.errors.join("; "), false);
    // 写面守卫：recipes/ 原件受保护时 service 另存工作副本并回传实际路径，
    // 后续运行/加载一律消费该路径（原件字节不变，TODO 增量②）
    if (r.recipe_path) {
      currentRecipe.recipe_path = r.recipe_path;
      if (r.workcopy) T.$("recipe-path").value = r.recipe_path;
    }
    T.msg(r.workcopy ? (r.message || `已另存工作副本: ${r.recipe_path}`) : "配方已保存", true);
    if (andRun) {
      const run = await T.api("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentRecipe.recipe_path, adapter: T.$("run-adapter").value }),
      });
      if (run.ok) { T.msg(`运行完成: cost=${run.cost}`, true); openRun(run.run_id); } // A4-C：单入口收编（hash 深链同步）
      else T.msg("运行失败: " + (run.errors || []).join("; "), false);
    }
  }
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 recipeCtx ════════════
   refresh=配方目录重拉（pageRecipe 幂等——壳判 innerHTML 已在即跳过；已加载
   配方/参数表/3D 预览不受扰——loadRecipe 只在点选/加载时触发）。无轮询面，
   leave 不需要。 */
export const recipeCtx = {
  refresh: () => pageRecipe(),
};
