/* rfauto 模板画廊页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移，
   PR-5）：模板卡 + 参数滑块 → 闭式即时预览（零 EM 求解）。 */

import { S, T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";

/* ═══ PR-5 模板画廊（ge8b Wave B 席B2）：模板卡 + 参数滑块 → 闭式即时预览 ═══
   映射/量程解释全在 service/gallery_service（前端只渲染）；预览数值全部
   出自 /api/calculators/run 闭式纯函数（零 EM 求解）；未配预览通道的
   模板如实显示，不硬凑。 */
export async function pageGallery() {
  const v = T.$("view-gallery");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>模板卡出自 TEMPLATE_META/TEMPLATE_NOMINAL（与 docs meta.yaml 同源）；<b>滑块改值 → 闭式计算器即时预览</b>（零 EM 求解）。</li>
      <li>闭式预览通道是<b>显式白名单</b>（当前 siw/slotline 线分析族）；未映射模板如实显示"未配通道"，不猜不硬凑。</li>
      <li>数值只在确定性内核（规则 7）：本页零物理数字产生，滑块初值=注册表名义参数。</li>`) +
    `<h2 class='page'>模板画廊 <small>交互卡 · 闭式即时预览（PR-5）</small></h2>
     <div class='toolbar'><input id='gal-filter' size='24' placeholder='按名称/拓扑过滤…'>
       <span id='gal-count' class='muted'></span></div>
     <div id='gal-grid' class='muted'>加载中...</div>
     <div id='gal-preview'></div>`;
  const d = await T.api("/api/gallery");
  const grid = T.$("gal-grid");
  if (!d.ok) { grid.innerHTML = `<span style="color:var(--err)">${esc((d.errors || []).join("; "))}</span>`; return; }
  S.galCards = d.cards || [];
  T.$("gal-count").textContent = `${d.n_templates} 模板 · ${d.n_previews} 配闭式预览通道`;
  const render = () => {
    const ft = T.$("gal-filter").value.trim().toLowerCase();
    const rows = S.galCards.filter((c) => !ft ||
      `${c.name} ${c.topology || ""}`.toLowerCase().includes(ft));
    grid.innerHTML = `<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(21rem,1fr));gap:10px'>` +
      rows.map((c) => `<div class='panel' style='margin:0'>
        <b>${esc(c.name)}</b> ${c.preview ? T.badge("闭式预览", "ok") : "<span class='muted' style='font-size:var(--text-xs)'>未配预览通道</span>"}
        ${c.f0_ghz ? `<span class='badge muted'>f0 ${esc(c.f0_ghz)} GHz</span>` : ""}
        <div class='muted' style='font-size:11.5px;margin:var(--space-1) 0'>${esc(c.topology || "")}</div>
        <div class='muted' style='font-size:var(--text-xs)'>${esc(Object.entries(c.nominal_params || {}).map(([k, x]) => k + "=" + x).join(" · "))}</div>
        ${c.preview ? `<button class='minor' style='margin-top:6px' data-gal='${escAttr(c.name)}'>打开预览</button>` : ""}
      </div>`).join("") + `</div>`;
    for (const btn of grid.querySelectorAll("[data-gal]"))
      btn.onclick = () => openPreview(btn.getAttribute("data-gal"));
  };
  T.$("gal-filter").oninput = render;
  async function openPreview(name) {
    const c = S.galCards.find((x) => x.name === name);
    const p = c && c.preview;
    const box = T.$("gal-preview");
    if (!p) { box.innerHTML = ""; return; }
    const meta = p.slider_meta || {};
    box.innerHTML = `<div class='panel' style='margin-top:var(--space-3)'>
      <b class='title'>闭式预览：${esc(c.name)} → <code>${esc(p.calculator)}</code></b>
      <div id='gal-sliders' style='margin:var(--space-2) 0'></div>
      <div class='toolbar'><button class='primary' id='gal-run'>计算</button>
        <span id='gal-msg' class='muted'></span></div>
      <div id='gal-result' class='muted' style='margin-top:var(--space-2)'>拖动滑块后点「计算」</div></div>`;
    const sliders = T.$("gal-sliders");
    const params = { ...p.params };
    const key = (s) => String(s).replace(/\W/g, "_"); // pg-s-* 惯例 id 消毒（UI-R11 P2-7）
    sliders.innerHTML = (p.sliders || []).map((k) => {
      const m = meta[k] || { min: params[k] * 0.5, max: params[k] * 1.5, step: Math.abs(params[k]) / 100, initial: params[k] };
      return `<label style='display:block;margin:6px 0'><b>${esc(k)}</b> <span id='gal-v-${escAttr(k)}'>${(+m.initial).toPrecision(6)}</span>
        <input type='range' id='gal-s-${key(k)}' data-k='${escAttr(k)}' min='${m.min}' max='${m.max}' step='${m.step}' value='${m.initial}' style='width:100%'></label>`;
    }).join("") || "<span class='muted'>本通道无可调滑块（固定参数直算）</span>";
    for (const input of sliders.querySelectorAll("input[type=range]"))
      input.oninput = () => {
        params[input.getAttribute("data-k")] = Number(input.value);
        const show = T.$("gal-v-" + input.getAttribute("data-k"));
        if (show) show.textContent = (+input.value).toPrecision(6);
      };
    T.$("gal-run").onclick = async () => {
      T.$("gal-msg").textContent = "计算中...";
      const r = await T.api("/api/calculators/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.calculator, params }) });
      T.$("gal-msg").textContent = "";
      const el = T.$("gal-result");
      if (!r.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((r.error || (r.errors || []).join("; ")))}</span>`; return; }
      el.innerHTML = "<table><tbody>" + Object.entries(r.result || r)
        .filter(([k]) => k !== "ok")
        .map(([k, x]) => `<tr><td><b>${esc(k)}</b></td><td>${esc(typeof x === "object" ? JSON.stringify(x) : String(x))}</td></tr>`).join("")
        + "</tbody></table>";
    };
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  render();
}
