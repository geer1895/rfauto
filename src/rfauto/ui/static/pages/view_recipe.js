/* rfauto 配方编辑页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   配方目录 + 参数表 + setup/optimization 表单化 + 3D 预览。 */

import { releaseWebGLIn } from "./charts.js";
import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// i18n（aurora_h W4-S1 壳层迁移 + 发布令 S3 残量清）：壳静态标签
// data-i18n+首扫、help 块分段 t()、动态串（目录行/表单标签/toast/aria）
// t() 烘焙——API 动态中文数据（d.help 文案/模型名）照旧 esc 不迁。
import { t, applyI18nRoot } from "./i18n.js";
import { bindClickRows, kitClickRowAttrs } from "./kit.js";
import { openRun } from "./router.js";
// P8-9（aurora_f W3-S9，R1 §面4）：T.api→apiFetch 统一请求层（本页 5 点）——
// 数据面（目录/配方加载/3D 预览数据）接 viewSignal("recipe") 切页收束 +
// aborted 短路（在途请求不再写隐藏区）；动作面（保存/运行 POST）保持
// 无 signal（用户显式动作不因切页取消），错误信封与 toast 呈现同形。
import { apiFetch, viewSignal } from "./api.js";

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
      <li><b>${t("recipe.help_1_core")}</b>${t("recipe.help_1_tail")}</li>
      <li><b>${t("recipe.help_2_core")}</b>${t("recipe.help_2_tail")}</li>
      <li><b>${t("recipe.help_3_core")}</b>${t("recipe.help_3_tail")}</li>
      <li>${t("recipe.help_4")}</li>`) +
    `<h2 class='page' data-i18n='recipe.title'>${t("recipe.title")}</h2>
      <div class='grid2'>
        <div class='panel'><b class='title' data-i18n='recipe.catalog_title'>${t("recipe.catalog_title")}</b><div id='recipe-cat' class='muted'>${t("recipe.loading")}</div></div>
        <div class='panel'><div class='toolbar' style="align-items:flex-start;flex-direction:column">${t("recipe.label_path")}
          <input id='recipe-path' style='width:100%' placeholder='recipes/wilkinson_pd_v1.yaml'>
          <button class='minor' id='recipe-load' data-i18n='recipe.load'>${t("recipe.load")}</button>
          <span class='muted'>${t("recipe.label_model")}<span id='recipe-model'>-</span></span></div>
        </div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title' data-i18n='recipe.params_title'>${t("recipe.params_title")}</b><table id='params-table'><thead>
          <tr><th scope="col">${t("recipe.th_name")}</th><th scope="col">${t("recipe.th_value")}</th><th scope="col">${t("recipe.th_unit")}</th><th scope="col">${t("recipe.th_bounds")}</th></tr></thead><tbody></tbody></table>
          <p class='toolbar'><button class='act' id='recipe-save' data-i18n='recipe.save'>${t("recipe.save")}</button>
          <button class='act' id='recipe-run' data-i18n='recipe.run_once'>${t("recipe.run_once")}</button>
          <select id='run-adapter'><option value='fake'>${t("recipe.opt_fake")}</option><option value='openems'>${t("recipe.opt_openems")}</option><option value='hfss'>${t("recipe.opt_hfss")}</option></select></p></div>
        <div class='panel'><b class='title' data-i18n='recipe.preview_title'>${t("recipe.preview_title")}</b><div id='recipe-3d'></div></div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title' data-i18n='recipe.setup_title'>${t("recipe.setup_title")}</b>
          <div id='setup-form' class='toolbar' style='flex-wrap:wrap;gap:var(--space-2)'></div>
          <details class='help' style='margin-top:var(--space-2)'><summary data-i18n='recipe.setup_advanced'>${t("recipe.setup_advanced")}</summary>
          <pre id='setup-pre' contenteditable='true' spellcheck='false'></pre></details></div>
        <div class='panel'><b class='title' data-i18n='recipe.opt_title'>${t("recipe.opt_title")}</b>
          <div id='opt-form'></div>
          <details class='help' style='margin-top:var(--space-2)'><summary data-i18n='recipe.opt_advanced'>${t("recipe.opt_advanced")}</summary>
          <pre id='opt-pre' contenteditable='true' spellcheck='false'></pre></details></div>
      </div>
      <div class='panel'><b class='title' data-i18n='recipe.help_title'>${t("recipe.help_title")}</b><div id='recipe-help' class='muted'></div></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W4-S1；幂等，动态容器走 t() 烘焙）
  T.$("recipe-load").onclick = loadRecipe;
  T.$("recipe-save").onclick = () => saveRecipe(false);
  T.$("recipe-run").onclick = () => saveRecipe(true);
  loadCatalog();

  async function loadCatalog() {
    const d = await apiFetch("/api/recipes", { signal: viewSignal("recipe") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const el = T.$("recipe-cat");
    const orig = d.recipes || [], work = d.workcopies || [];
    // UI-R4：目录行键盘可达（div 行 role=button 缺省；aria-label 行动作——
    // path 经 kit escAttr 出口转义）
    const row = (r, isWorkcopy) =>
      `<div class="clickable" style="padding:5px 8px;border-radius:var(--radius-xs)" data-p="${escAttr(r.path)}" ${kitClickRowAttrs({ label: t("recipe.row_open_aria") + (r.path || "") })}>
        <b>${esc(r.path.split("/").pop())}</b> ${isWorkcopy ? T.badge(t("recipe.workcopy_badge"), "warn") + " " : ""}<span class="muted">${esc(r.model)}</span><br>
        <span class="muted" style="font-size:11.5px">${esc(r.n_params ?? "?")}${t("recipe.row_params_sep")}${esc(r.n_objectives ?? "?")}${t("recipe.row_obj_band")}${esc(JSON.stringify(r.freq_range))}</span></div>`;
    // C22 分组：recipes/ 原件在上；工作副本（runs/recipe_workcopy/）单独分组，
    // 标注「工作副本」并给人工审阅入库提示（rfauto inbox 审批链，前端只渲染）。
    el.innerHTML =
      `<div style="margin-bottom:var(--space-1)"><b>${t("recipe.orig_head")}</b> <span class="muted" style="font-size:11.5px">${orig.length}${t("recipe.count_suffix")}</span></div>` +
      orig.map((r) => row(r, false)).join("") +
      (work.length ?
        `<div style="margin:10px 0 4px"><b>${t("recipe.workcopy_head")}</b> <span class="muted" style="font-size:11.5px">${work.length}${t("recipe.count_suffix")}</span></div>` +
        `<div class="muted" style="font-size:11.5px;margin:0 0 4px">${t("recipe.review_lead")}<b>rfauto inbox</b>${t("recipe.review_mid")}</div>` +
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
    const val = await apiFetch("/api/recipe?path=" + encodeURIComponent(T.$("recipe-path").value.trim()),
      { signal: viewSignal("recipe") });
    if (val.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    if (!val.ok) return T.msg(val.errors.join("; "), false);
    currentRecipe = val;
    // 人性化三批（2026-10-19 审计 ⚠3）：加载成功给正反馈 toast（msg 区单点
    // 复用——成功消息即覆写先前的"路径为空"类错误残留）；xxx=文件名尾段。
    T.msg(t("recipe.loaded_ok") +
      String(val.recipe_path || T.$("recipe-path").value.trim()).split(/[\\/]/).pop(), true);
    // C22：工作副本视图标注（service 端 is_workcopy/review_hint，前端只渲染）
    T.$("recipe-model").textContent =
      `${val.model}${t("recipe.tpl_lead")}${val.template_hint || t("recipe.no_template")}${t("recipe.tpl_tail")}` + (val.is_workcopy ? t("recipe.workcopy_suffix") : "");
    T.$("recipe-model").title = val.is_workcopy ? (val.review_hint || "") : "";
    const tb = T.$("params-table").tBodies[0];
    tb.innerHTML = "";
    for (const p of val.params) {
      const bounds = p.bounds ? `[${p.bounds.join(", ")}]`
        : (val.optimization.params[p.name] ? `[${val.optimization.params[p.name].low}, ${val.optimization.params[p.name].high}]` : "-");
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(p.name)}</td><td><input id="rp-param-${key(p.name)}" data-param="${escAttr(p.name)}" value="${escAttr(p.value ?? "")}" size="10" aria-label="${t("recipe.param_aria_lead")}${escAttr(p.name)}${t("recipe.param_aria_tail")}"></td><td>${esc(p.unit || "")}</td><td class="muted">${esc(bounds)}</td>`;
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
      ["solver", t("recipe.f_solver"), setup.solver ?? "", "text"],
      ["f0", t("recipe.f_f0"), fr[0] ?? "", "number"],
      ["f1", t("recipe.f_f1"), fr[1] ?? "", "number"],
      ["points", t("recipe.f_points"), setup.points ?? "", "number"],
      ["convergence_delta", t("recipe.f_conv"), setup.convergence_delta ?? "", "number"],
      ["radiation_box", t("recipe.f_radbox"), setup.radiation_box ?? "", "text"],
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
    if (!names.length) { form.innerHTML = "<span class='muted'>" + t("recipe.no_opt_params") + "</span>"; return; }
    form.innerHTML = `<table><thead><tr><th scope="col">${t("recipe.th_tune_var")}</th><th scope="col">low</th><th scope="col">high</th></tr></thead><tbody>` +
      names.map((n) => {
        const p = opt.params[n] || {};
        return `<tr><td><b>${esc(n)}</b></td>
          <td><input id="rp-opt-${key(n)}-low" class="opt-b" data-param="${escAttr(n)}" data-k="low" value="${escAttr(p.low ?? "")}" size="9" type="number" step="any" aria-label="${escAttr(n)}${t("recipe.opt_low_aria")}"></td>
          <td><input id="rp-opt-${key(n)}-high" class="opt-b" data-param="${escAttr(n)}" data-k="high" value="${escAttr(p.high ?? "")}" size="9" type="number" step="any" aria-label="${escAttr(n)}${t("recipe.opt_high_aria")}"></td></tr>`;
      }).join("") + "</tbody></table>" +
      `<div class="muted" style="margin-top:var(--space-1);font-size:11.5px">${t("recipe.opt_hint")}</div>`;
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
    const r = await apiFetch("/api/model3d", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: currentRecipe.template_hint, params }),
      signal: viewSignal("recipe"),
    });
    if (r.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    releaseWebGLIn(T.$("recipe-3d")); // P0-4 防御式：弃置上一代 WebGL 上下文
    T.drawBoxes(T.$("recipe-3d"), r);
  }

  async function saveRecipe(andRun) {
    if (!currentRecipe) return T.msg(t("recipe.load_first"), false);
    const updates = { params: {} };
    document.querySelectorAll("#params-table input[data-param]").forEach((el) => {
      const raw = el.value.trim();
      updates.params[el.dataset.param] = isNaN(Number(raw)) || raw === "" ? raw : Number(raw);
    });
    try { updates.setup = JSON.parse(T.$("setup-pre").textContent); }
    catch { return T.msg(t("recipe.setup_bad_json"), false); }
    try {
      const opt = JSON.parse(T.$("opt-pre").textContent);
      updates.objectives = opt.objectives; updates.optimization = opt.optimization;
    } catch { return T.msg(t("recipe.opt_bad_json"), false); }
    const r = await apiFetch("/api/recipe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentRecipe.recipe_path, updates }),
    });
    if (!r.ok) return T.msg(t("recipe.save_rejected") + r.errors.join("; "), false);
    // 写面守卫：recipes/ 原件受保护时 service 另存工作副本并回传实际路径，
    // 后续运行/加载一律消费该路径（原件字节不变，TODO 增量②）
    if (r.recipe_path) {
      currentRecipe.recipe_path = r.recipe_path;
      if (r.workcopy) T.$("recipe-path").value = r.recipe_path;
    }
    T.msg(r.workcopy ? (r.message || t("recipe.saved_workcopy") + r.recipe_path) : t("recipe.saved"), true);
    if (andRun) {
      const run = await apiFetch("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentRecipe.recipe_path, adapter: T.$("run-adapter").value }),
        timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：同步 run_once 分钟级
      });
      // 人性化三批（2026-10-19 审计 ⚠5）：cost 浮点截断 4 位小数——此前
      // 15 位全精度直出（cost=7.424965102246688）不可读。
      if (run.ok) {
        T.msg(t("recipe.run_done") +
          (typeof run.cost === "number" ? run.cost.toFixed(4) : run.cost), true);
        openRun(run.run_id); // A4-C：单入口收编（hash 深链同步）
      } else T.msg(t("recipe.run_failed") + (run.errors || []).join("; "), false);
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
