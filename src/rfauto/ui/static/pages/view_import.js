/* rfauto 工程导入页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   HFSS .aedt → 设计规格 → 配方草稿。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { fileBrowser } from "./filebrowser.js";

/* ═══ 工程导入（HFSS .aedt → 配方草稿）═══ */
let importSpec = null;

export async function pageImport() {
  const v = T.$("view-import");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>工程文件</b>：点「浏览」选 .aedt（也可手输路径）；版本留空=跟随服务端缺省（以实装版本为准）。</li>
      <li><b>读取工程</b> 后列出设计变量：勾选哪些进优化空间、编辑 low/high（默认取 HFSS Optimetrics 扫参范围，没有则 ±20%）。</li>
      <li><b>保存配方草稿</b> 后到「配方编辑」页补目标（objectives），再进「优化调参」。</li>
      <li>依赖变量（表达式引用其它变量）与非数值变量自动排除。</li>`) +
    `<h2 class='page'>工程导入 <small>HFSS .aedt → 设计规格 → 配方草稿</small></h2>
      <div class='panel'><div class='toolbar'>
        工程文件: <input id='imp-project' style="flex:1;min-width:280px" placeholder='hfss_projects/xxx.aedt'>
        <button class='minor' id='imp-browse'>浏览…</button>
        设计名: <input id='imp-design' size='12' placeholder='留空取第一个'>
        版本: <select id='imp-version'><option value=''>服务端缺省（2025.1）</option><option value='2025.1'>2025.1</option><option value='__custom__'>自定义…</option></select>
        <input id='imp-version-custom' size='7' placeholder='如 2025.2' style="display:none">
        <button class='act' id='imp-read'>读取工程</button>
      </div><div id='imp-msg' class='muted'>首次启动 AEDT 需约 30 秒；读取前请确认工程未被其它 AEDT 窗口占用（残留 .lock 会导致失败）。</div></div>
      <div id='imp-spec'></div>`;
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
    btn.disabled = true; btn.textContent = "读取中...（首次启动 AEDT 需 ~30s）";
    T.$("imp-msg").textContent = "";
    const body = { project: T.$("imp-project").value.trim(),
                   design: T.$("imp-design").value.trim() || null };
    const ver = impVersionValue();
    if (ver) body.version = ver; // 空串=不透传（服务端缺省钉生效）
    importSpec = await T.api("/api/hfss/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    btn.disabled = false; btn.textContent = "读取工程";
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
      const src = rng ? T.badge("扫参范围", "ok") : T.badge("±20%", "muted");
      return `<tr>
        <td><input type="checkbox" id="imp-include-${key(n)}" class="imp-include" data-n="${escAttr(n)}" ${dis ? "" : "checked"} ${dis ? "disabled" : ""}></td>
        <td>${esc(n)}</td><td class="muted">${esc(info.expression)}</td>
        <td><input id="imp-low-${key(n)}" class="imp-low" data-n="${escAttr(n)}" value="${escAttr(low)}" size="9" ${dis ? "disabled" : ""}></td>
        <td><input id="imp-high-${key(n)}" class="imp-high" data-n="${escAttr(n)}" value="${escAttr(high)}" size="9" ${dis ? "disabled" : ""}></td>
        <td>${rng ? esc(rng.start + " ~ " + rng.stop + " (step " + rng.step + ")") : src}</td>
      </tr>`;
    }).join("");
    T.$("imp-spec").innerHTML = `
      <div class='panel'><b class='title'>设计规格 — ${esc(s.design || "?")}（${names.length} 个变量，${Object.keys(s.parametrics || {}).length} 个已有扫参范围）</b>
      <table><thead><tr><th scope="col"></th><th scope="col">变量</th><th scope="col">表达式</th><th scope="col">low</th><th scope="col">high</th><th scope="col">来源</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class='grid2'>
        <div class='panel'><b class='title'>端口 / Setup</b>
          <div>${(s.ports || []).map((p) => `${esc(p.name)} <span class="muted">${esc(p.type)}</span>`).join("<br>") || "<span class='muted'>无端口边界</span>"}</div>
          <div class="muted" style="margin-top:var(--space-2)">Setup: ${esc(s.setup?.setup_name || "无")}；Sweep: ${(s.setup?.sweeps || []).map((w) => esc(w.range_start + "~" + w.range_end)).join("、") || "无"}</div>
        </div>
        <div class='panel'><b class='title'>生成配方</b>
          <div class="toolbar">目标文件: <input id='imp-out' size='30' value='recipes/custom/imported.yaml'>
          <button class='minor' id='imp-out-browse'>浏览…</button>
          <button class='act' id='imp-save'>保存配方草稿</button></div>
          <div id='imp-saved'></div>
          <div class="muted" style="margin-top:var(--space-2)">保存后到「配方编辑」页加载它，补 objectives（什么算"好"）再调参。</div>
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
    const r = await T.api("/api/hfss/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) return T.msg("导入失败: " + r.error, false);
    // 用客户端编辑后的 params 覆盖保存（服务端 out 只含默认范围）
    await fetch("/api/recipe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: outPath, create: {
        ...importSpec.recipe, params,
        hfss_var_map: Object.fromEntries(Object.keys(params).map((n) => [n, n])),
      } }) });
    T.$("imp-saved").innerHTML = T.badge("已保存", "ok") + ` <span class="muted">${escAttr(outPath)}</span>`;
    T.msg("配方草稿已生成", true);
  }
}
