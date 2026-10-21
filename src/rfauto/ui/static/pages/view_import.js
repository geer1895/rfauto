/* rfauto 工程导入页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）：
   HFSS .aedt → 设计规格 → 配方草稿。
   i18n（发布前置软编码批 S1 全清）：壳/help 块分段 t()、工具条标签/
   下拉选项/占位符/规格表/配方生成面板/提示与 toast 全迁词表（import.*
   键域，zh 与旧字面逐字节同、en 新增）——拼接数据段（设计名/变量名/
   错误串）照旧 esc 后拼模板，词表值零 HTML；壳静态标签 data-i18n-ph
   （placeholder 注入口）+applyI18nRoot 首扫；renderSpec 动态容器一律
   t() 烘焙不挂 data-i18n（头注纪律）。__custom__ 协议哨兵值/hfss_projects
   示例路径/recipes/custom/imported.yaml 缺省输出路径/low/high 协议列名
   等与服务端对齐的标识符保留原文（view_tools TOOL_GROUP_FALLBACK 豁免
   同族）。 */

import { T } from "./context.js";
import { errorText, esc, escAttr, help } from "./dom.js";
import { fileBrowser } from "./filebrowser.js";
// i18n（S1 全清）：壳静态标签 data-i18n+首扫；动态容器文案 t() 渲染期烘焙。
import { t, applyI18nRoot } from "./i18n.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 2 点
// T.api + 1 点裸 fetch 同批收敛）——全页皆用户动作 POST（读取工程/保存配方
// 草稿），保持无 signal（用户动作不被切页取消；首次启动 AEDT 读取 ~30s 更
// 不可中断）。apiFetch 永不抛——保存草稿尾段信封消费走 errorText 回退链
// （审查波 2 P3-4 清偿：error_envelope 只有 errors 列表，旧裸读单数 error
// 键渲染 "undefined"；旧代码同病，此处为顺手清偿非迁移引入）。
import { apiFetch } from "./api.js";

/* ═══ 工程导入（HFSS .aedt → 配方草稿）═══ */
let importSpec = null;

export async function pageImport() {
  const v = T.$("view-import");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>${t("import.help_1_core")}</b>${t("import.help_1_tail")}</li>
      <li><b>${t("import.read")}</b>${t("import.help_2_tail")}</li>
      <li><b>${t("import.save")}</b>${t("import.help_3_tail")}</li>
      <li>${t("import.help_4")}</li>`) +
    `<h2 class='page'><span data-i18n='import.title'>${t("import.title")}</span> <small data-i18n='import.subtitle'>${t("import.subtitle")}</small></h2>
      <div class='panel'><div class='toolbar'>
        ${t("import.project_label")}<input id='imp-project' style="flex:1;min-width:280px" placeholder='hfss_projects/xxx.aedt'>
        <button class='minor' id='imp-browse' data-i18n='import.browse'>${t("import.browse")}</button>
        ${t("import.design_label")}<input id='imp-design' size='12' data-i18n-ph='import.design_ph' placeholder='${t("import.design_ph")}'>
        ${t("import.version_label")}<select id='imp-version'><option value=''>${t("import.ver_default")}</option><option value='2025.1'>2025.1</option><option value='__custom__'>${t("import.ver_custom")}</option></select>
        <input id='imp-version-custom' size='7' data-i18n-ph='import.ver_custom_ph' placeholder='${t("import.ver_custom_ph")}' style="display:none">
        <button class='act' id='imp-read' data-i18n='import.read'>${t("import.read")}</button>
      </div><div id='imp-msg' class='muted'>${t("import.msg_hint")}</div></div>
      <div id='imp-spec'></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（S1 全清；幂等，动态容器走 t() 烘焙）
  T.$("imp-read").onclick = readProject;
  T.$("imp-browse").onclick = () =>
    fileBrowser("", (p) => { T.$("imp-project").value = p; });
  T.$("imp-version").onchange = () => { // 自定义版本输入框随下拉显隐
    T.$("imp-version-custom").style.display =
      T.$("imp-version").value === "__custom__" ? "" : "none";
  };

  /* 导入版本取值（P0-A，R6 F-3）：下拉空值=跟随服务端缺省钉（不透传显式
     版本——旧下拉钉死两个未安装的旧版本号且显式透传，把 server 缺省钉整个
     旁路，真机必请求未安装的 AEDT）；自定义输入优先于下拉显式项；恒空串时
     请求体不带 version 键。 */
  function impVersionValue() {
    const sel = T.$("imp-version").value;
    if (sel === "__custom__") return T.$("imp-version-custom").value.trim();
    return sel;
  }

  async function readProject() {
    const btn = T.$("imp-read");
    btn.disabled = true; btn.textContent = t("import.reading");
    T.$("imp-msg").textContent = "";
    const body = { project: T.$("imp-project").value.trim(),
                   design: T.$("imp-design").value.trim() || null };
    const ver = impVersionValue();
    if (ver) body.version = ver; // 空串=不透传（服务端缺省钉生效）
    importSpec = await apiFetch("/api/hfss/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：AEDT 工程读取分钟级
    });
    btn.disabled = false; btn.textContent = t("import.read");
    if (!importSpec.ok) { T.$("imp-msg").innerHTML = `<span style="color:var(--err)">${esc(importSpec.error)}</span>`; return; }
    renderSpec();
  }

  function renderSpec() {
    const s = importSpec.spec, vars = s.variables || {};
    const names = Object.keys(vars);
    // UI-R11（A6 P2-7 可测试性半边）：行内控件按 pg-s-* 惯例补 id（key()
    // 把 HFSS 变量名消毒为选择器稳健形态；class/data-* 消费位不动）
    const key = (v) => String(v).replace(/\W/g, "_");
    const rows = names.map((n) => {
      const info = vars[n];
      const rng = (s.parametrics || {})[n];
      const val = parseFloat(info.value);
      const dis = info.dependent || isNaN(val);
      const low = rng ? rng.start : (isNaN(val) ? "" : (val * 0.8).toPrecision(4));
      const high = rng ? rng.stop : (isNaN(val) ? "" : (val * 1.2).toPrecision(4));
      const src = rng ? T.badge(t("import.range_sweep"), "ok") : T.badge("±20%", "muted");
      return `<tr>
        <td><input type="checkbox" id="imp-include-${key(n)}" class="imp-include" data-n="${escAttr(n)}" ${dis ? "" : "checked"} ${dis ? "disabled" : ""}></td>
        <td>${esc(n)}</td><td class="muted">${esc(info.expression)}</td>
        <td><input id="imp-low-${key(n)}" class="imp-low" data-n="${escAttr(n)}" value="${escAttr(low)}" size="9" ${dis ? "disabled" : ""}></td>
        <td><input id="imp-high-${key(n)}" class="imp-high" data-n="${escAttr(n)}" value="${escAttr(high)}" size="9" ${dis ? "disabled" : ""}></td>
        <td>${rng ? esc(rng.start + " ~ " + rng.stop + " (step " + rng.step + ")") : src}</td>
      </tr>`;
    }).join("");
    T.$("imp-spec").innerHTML = `
      <div class='panel'><b class='title'>${t("import.spec_title")}${esc(s.design || "?")}${t("import.spec_vars_pre")}${names.length}${t("import.spec_vars_mid")}${Object.keys(s.parametrics || {}).length}${t("import.spec_range_mid")}</b>
      <table><thead><tr><th scope="col"></th><th scope="col">${t("import.th_variable")}</th><th scope="col">${t("import.th_expression")}</th><th scope="col">low</th><th scope="col">high</th><th scope="col">${t("import.th_source")}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class='grid2'>
        <div class='panel'><b class='title'>${t("import.ports_title")}</b>
          <div>${(s.ports || []).map((p) => `${esc(p.name)} <span class="muted">${esc(p.type)}</span>`).join("<br>") || `<span class='muted'>${t("import.no_ports")}</span>`}</div>
          <div class="muted" style="margin-top:var(--space-2)">Setup: ${esc(s.setup?.setup_name || t("import.none"))}；Sweep: ${(s.setup?.sweeps || []).map((w) => esc(w.range_start + "~" + w.range_end)).join("、") || t("import.none")}</div>
        </div>
        <div class='panel'><b class='title'>${t("import.recipe_title")}</b>
          <div class="toolbar">${t("import.out_label")}<input id='imp-out' size='30' value='recipes/custom/imported.yaml'>
          <button class='minor' id='imp-out-browse'>${t("import.browse")}</button>
          <button class='act' id='imp-save'>${t("import.save")}</button></div>
          <div id='imp-saved'></div>
          <div class="muted" style="margin-top:var(--space-2)">${t("import.save_hint")}</div>
        </div>
      </div>`;
    T.$("imp-save").onclick = saveRecipeDraft;
    T.$("imp-out-browse").onclick = () =>
      fileBrowser("", (p) => {
        if (!p.endsWith(".yaml")) p = p + "/imported.yaml";
        T.$("imp-out").value = p.replace(/\\/g, "/");
      });
  }

  async function saveRecipeDraft() {
    const params = {};
    document.querySelectorAll("#imp-spec .imp-include").forEach((cb) => {
      if (!cb.checked) return;
      const n = cb.dataset.n;
      const lo = document.querySelector(`.imp-low[data-n="${n}"]`).value.trim();
      const hi = document.querySelector(`.imp-high[data-n="${n}"]`).value.trim();
      const f = (x) => parseFloat(x) || 0;
      params[n] = { value: parseFloat(importSpec.spec.variables[n].value) || 0, low: f(lo), high: f(hi) };
    });
    const outPath = T.$("imp-out").value.trim();
    const body = { project: importSpec.project, design: importSpec.design,
                   out: outPath };
    const ver = impVersionValue();
    if (ver) body.version = ver; // 与读取工程同口径：空串不透传
    const r = await apiFetch("/api/hfss/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：几何导入+配方生成分钟级
    });
    // UI-R11 A6 P2-3 同款收编（审查波 2 P3-4 清偿）：error_envelope 只有
    // errors 列表，裸读单数 error 键会渲染 "导入失败: undefined"——走
    // errorText 回退链（errors→error→reason，filebrowser.js 同面先例）。
    if (!r.ok) return T.msg(t("import.fail_lead") + errorText(r), false);
    // 用客户端编辑后的 params 覆盖保存（服务端 out 只含默认范围）
    await apiFetch("/api/recipe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: outPath, create: {
        ...importSpec.recipe, params,
        hfss_var_map: Object.fromEntries(Object.keys(params).map((n) => [n, n])),
      } }) });
    T.$("imp-saved").innerHTML = T.badge(t("import.saved_badge"), "ok") + ` <span class="muted">${escAttr(outPath)}</span>`;
    T.msg(t("import.saved_msg"), true);
  }
}
