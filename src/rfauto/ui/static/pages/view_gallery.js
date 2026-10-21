/* rfauto 模板画廊页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移，
   PR-5）：模板卡 + 参数滑块 → 闭式即时预览（零 EM 求解）。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// 三态收敛（架构批 W2-S5，R1 #8 批1）：错误=kitErrorPanel、空态=kitEmptyState
import { kitEmptyState, kitErrorPanel } from "./kit.js";
// i18n（架构批 W1-S2 试点页 2）：壳标签 data-i18n+首扫；卡面/预览面板随
// 数据重建，文案一律 t() 渲染期烘焙（i18n.js 头注纪律）。
import { t, applyI18nRoot } from "./i18n.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 2 点）——
// 数据面（模板卡清单）接 viewSignal("gallery") 切页收束 + aborted 短路；动作
// 面（闭式预览计算 POST）保持无 signal（用户动作不被切页取消）。信封消费
// 形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* 模板卡缓存（W6-S2 S 状态收编：原 S.galCards 单模块私有键降级模块级
   ——属主=本模块，契约表见 context.js；进页重拉语义不变）。 */
let _galCards = null;

/* ═══ PR-5 模板画廊（ge8b Wave B 席B2）：模板卡 + 参数滑块 → 闭式即时预览 ═══
   映射/量程解释全在 service/gallery_service（前端只渲染）；预览数值全部
   出自 /api/calculators/run 闭式纯函数（零 EM 求解）；未配预览通道的
   模板如实显示，不硬凑。 */
export async function pageGallery() {
  const v = T.$("view-gallery");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("gallery.help_1_lead")}<b>${t("gallery.help_1_core")}</b>${t("gallery.help_1_tail")}</li>
      <li>${t("gallery.help_2_lead")}<b>${t("gallery.help_2_core")}</b>${t("gallery.help_2_tail")}</li>
      <li>${t("gallery.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='gallery.title'>${t("gallery.title")}</span> <small data-i18n='gallery.subtitle'>${t("gallery.subtitle")}</small></h2>
     <div class='toolbar'><input id='gal-filter' size='24' placeholder='${t("gallery.filter_placeholder")}' data-i18n-ph='gallery.filter_placeholder'>
       <span id='gal-count' class='muted'></span></div>
     <div id='gal-grid' class='muted'>${t("gallery.loading")}</div>
     <div id='gal-preview'></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W1-S2）
  const d = await apiFetch("/api/gallery", { signal: viewSignal("gallery") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const grid = T.$("gal-grid");
  if (!d.ok) {
    // 三态收敛（架构批 W2-S5，R1 #8 批1）：加载失败=kitErrorPanel 带重试
    //（重试=整页重进，pageGallery 幂等：壳判 innerHTML 已在即跳过）
    grid.innerHTML = kitErrorPanel((d.errors || []).join("; "), "gal-retry");
    const rb = T.$("gal-retry");
    if (rb) rb.onclick = () => pageGallery();
    return;
  }
  _galCards = d.cards || [];
  T.$("gal-count").textContent = t("gallery.count_tpl", { n: d.n_templates, p: d.n_previews });
  const render = () => {
    const ft = T.$("gal-filter").value.trim().toLowerCase();
    const rows = _galCards.filter((c) => !ft ||
      `${c.name} ${c.topology || ""}`.toLowerCase().includes(ft));
    if (!rows.length) {
      // 三态收敛（R1 #8 批1）：过滤零命中=kitEmptyState（文案 t() 渲染期烘焙）
      grid.innerHTML = kitEmptyState(t("gallery.empty_filter"));
      return;
    }
    grid.innerHTML = `<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(21rem,1fr));gap:10px'>` +
      rows.map((c) => `<div class='panel' style='margin:0'>
        <b>${esc(c.name)}</b> ${c.preview ? T.badge(t("gallery.preview_badge"), "ok") : `<span class='muted' style='font-size:var(--text-xs)'>${t("gallery.no_preview")}</span>`}
        ${c.f0_ghz ? `<span class='badge muted'>f0 ${esc(c.f0_ghz)} GHz</span>` : ""}
        <div class='muted' style='font-size:11.5px;margin:var(--space-1) 0'>${esc(c.topology || "")}</div>
        <div class='muted' style='font-size:var(--text-xs)'>${esc(Object.entries(c.nominal_params || {}).map(([k, x]) => k + "=" + x).join(" · "))}</div>
        ${c.preview ? `<button class='minor' style='margin-top:6px' data-gal='${escAttr(c.name)}'>${t("gallery.open_preview")}</button>` : ""}
      </div>`).join("") + `</div>`;
    for (const btn of grid.querySelectorAll("[data-gal]"))
      btn.onclick = () => openPreview(btn.getAttribute("data-gal"));
  };
  T.$("gal-filter").oninput = render;
  async function openPreview(name) {
    const c = _galCards.find((x) => x.name === name);
    const p = c && c.preview;
    const box = T.$("gal-preview");
    if (!p) { box.innerHTML = ""; return; }
    const meta = p.slider_meta || {};
    box.innerHTML = `<div class='panel' style='margin-top:var(--space-3)'>
      <b class='title'>${t("gallery.preview_prefix")}${esc(c.name)} → <code>${esc(p.calculator)}</code></b>
      <div id='gal-sliders' style='margin:var(--space-2) 0'></div>
      <div class='toolbar'><button class='primary' id='gal-run'>${t("gallery.compute")}</button>
        <span id='gal-msg' class='muted'></span></div>
      <div id='gal-result' class='muted' style='margin-top:var(--space-2)'>${t("gallery.result_hint")}</div></div>`;
    const sliders = T.$("gal-sliders");
    const params = { ...p.params };
    const key = (s) => String(s).replace(/\W/g, "_"); // pg-s-* 惯例 id 消毒（UI-R11 P2-7）
    sliders.innerHTML = (p.sliders || []).map((k) => {
      const m = meta[k] || { min: params[k] * 0.5, max: params[k] * 1.5, step: Math.abs(params[k]) / 100, initial: params[k] };
      return `<label style='display:block;margin:6px 0'><b>${esc(k)}</b> <span id='gal-v-${escAttr(k)}'>${(+m.initial).toPrecision(6)}</span>
        <input type='range' id='gal-s-${key(k)}' data-k='${escAttr(k)}' min='${m.min}' max='${m.max}' step='${m.step}' value='${m.initial}' style='width:100%'></label>`;
    }).join("") || "<span class='muted'>" + t("gallery.no_sliders") + "</span>";
    for (const input of sliders.querySelectorAll("input[type=range]"))
      input.oninput = () => {
        params[input.getAttribute("data-k")] = Number(input.value);
        const show = T.$("gal-v-" + input.getAttribute("data-k"));
        if (show) show.textContent = (+input.value).toPrecision(6);
      };
    T.$("gal-run").onclick = async () => {
      T.$("gal-msg").textContent = t("gallery.computing");
      const r = await apiFetch("/api/calculators/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.calculator, params }),
        timeoutMs: 0 }); // 长跑豁免（P9-11 缺省超时）：计算器真算时长不定
      T.$("gal-msg").textContent = "";
      const el = T.$("gal-result");
      // 三态收敛（R1 #8 批1）：闭式计算失败=kitErrorPanel（原裸 ✗ span，
      // 形态②清偿；重触发=「计算」钮，不加重试钮防双发）
      if (!r.ok) { el.innerHTML = kitErrorPanel(r.error || (r.errors || []).join("; ")); return; }
      el.innerHTML = "<table><tbody>" + Object.entries(r.result || r)
        .filter(([k]) => k !== "ok")
        .map(([k, x]) => `<tr><td><b>${esc(k)}</b></td><td>${esc(typeof x === "object" ? JSON.stringify(x) : String(x))}</td></tr>`).join("")
        + "</tbody></table>";
    };
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  render();
}

/* ═══ R-1（架构批 W3-S12）：PageContext 增量钩子 galleryCtx ═══════════
   refresh=模板卡数据重拉（pageGallery 幂等：壳判 innerHTML 已在即跳过，
   /api/gallery 重拉后按当前过滤词重铺网格；过滤输入值与已打开的闭式预览
   面保持）。无轮询面，leave 不需要。 */
export const galleryCtx = {
  refresh: () => pageGallery(),
};
