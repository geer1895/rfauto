/* rfauto 使用指南页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）。
   i18n（aurora_g W2-S1 批 4，R1 §面2 P9-5）：纯静态页整页分段 t() 迁入
   （guide.*，zh 与旧字面逐字节同、en 新增）——本页零 API 数据，结构
   （<li>/<b>/<table>/guide-flow）留模板、纯文本段进词表（view_dashboard
   help 块分段先例）；值内 &lt;/&gt; 为渲染保真的字符实体（深链示例/
   S11&lt;-15dB），非标签。

   W3.5-K2 人性化二批（2026-10-19）深度扩展：概念导览 → 完整工作流教程——
   ①页顶新增锚点目录（.guide-toc，g-* 锚点）：页内跳转点击 preventDefault +
   文档绝对坐标直设 scrollTop（人性化三批改——原 scrollIntoView smooth 实测
   不可靠，见 _bindToc 注），**不写 location.hash**——hash 是两级路由信道
   （router.js parseRoute 仅认 ^#/ 形态），裸 #anchor 会污染路由态；
   委托监听经 dataset 去重挂本页容器（容器跨渲染复用，重渲零叠加），
   各节标题行右侧带「↑ 目录」回跳锚。②新增「第一个真实工作流」四节
   走查（g-wf1 配方从哪来 / g-wf2 Tune 页通道决策表 / g-wf3 结果判读 +
   fake 数字第一疑问 / g-wf4 进阶三段），每步给「在哪个页面点哪个按钮」
   的具体指路（按钮名与 tune/recipe/import/queue 各页词表键逐字对齐）；
   新增文案全部进词表 guide.toc* 与 guide.wf* 键（zh/en 双语同笔），本文件零
   CJK 字面量（hardcode 棘轮基线=0 口径不变）。 */

import { T } from "./context.js";
import { help } from "./dom.js";
import { t, applyI18nRoot } from "./i18n.js";

/* 「↑ 目录」回跳锚（各节标题行右侧；跳转行为委托 _bindToc）。 */
function _back() {
  return `<a class='muted' style='float:right;font-size:12px' href='#g-toc' data-goto='g-toc'>↑ ${t("guide.toc_title")}</a>`;
}

/* 锚点目录跳转（W3.5-K2）：委托监听挂本页容器（dataset 去重防重渲叠加）；
   点击锚链接 preventDefault 后跳转。
   人性化三批（2026-10-19 审计 ⚠2）：scrollIntoView(smooth) 实测不可靠——
   全局 html{scroll-behavior:smooth}（index.html:199）与 SPA 布局位移叠加，
   出现 2s 零滚动/反向上滚且目标未入视口。改文档绝对坐标直设 scrollTop
   （window.scrollTo 行为字面量 "instant" 强制即时跳转——CSS 平滑与动画
   中断面一并消除；旧引擎对未知行为字面量抛 TypeError 时降级两参形态，
   仍为同容器直设，可靠性不回退）。 */
function _bindToc(v) {
  if (v.dataset.tocBound) return;
  v.dataset.tocBound = "1";
  v.addEventListener("click", (ev) => {
    const tgt = ev.target;
    const a = tgt && tgt.closest ? tgt.closest("a[data-goto]") : null;
    if (!a) return;
    const el = document.getElementById(a.getAttribute("data-goto"));
    if (!el) return;
    ev.preventDefault();
    const top = el.getBoundingClientRect().top +
      (window.scrollY || window.pageYOffset || 0) - 12; // 12px 顶部留白
    try { window.scrollTo({ top, left: 0, behavior: "instant" }); }
    catch { window.scrollTo(0, top); }
  });
}

/* ═══ 使用指南 ═══ */
export function pageGuide() {
  const v = T.$("view-guide");
  v.innerHTML = help(`
    <li>${t("guide.help_1")}</li>
    <li>${t("guide.help_2")}</li>`) +
    `<h2 class='page'>${t("guide.title")} <small>${t("guide.subtitle")}</small></h2>
    <div class='panel' id='g-toc'><b class='title'>${t("guide.toc_title")}</b>
      <nav class='guide-toc' style='margin:var(--space-2) 0;font-size:var(--text-xs)'>
        <a style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) 0' href='#g-what' data-goto='g-what'>${t("guide.what_title")}</a>
        <a style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) 0' href='#g-steps' data-goto='g-steps'>${t("guide.steps_title")}</a>
        <a style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) 0;font-weight:600' href='#g-wf' data-goto='g-wf'>${t("guide.wf_title")}</a>
        <a class='muted' style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) var(--space-4)' href='#g-wf1' data-goto='g-wf1'>${t("guide.wf1_t")}</a>
        <a class='muted' style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) var(--space-4)' href='#g-wf2' data-goto='g-wf2'>${t("guide.wf2_t")}</a>
        <a class='muted' style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) var(--space-4)' href='#g-wf3' data-goto='g-wf3'>${t("guide.wf3_t")}</a>
        <a class='muted' style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) var(--space-4)' href='#g-wf4' data-goto='g-wf4'>${t("guide.wf4_t")}</a>
        <a style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) 0' href='#g-gloss' data-goto='g-gloss'>${t("guide.gl_title")}</a>
        <a style='display:inline-block;margin:var(--space-2) var(--space-3) var(--space-2) 0' href='#g-faq' data-goto='g-faq'>${t("guide.faq_title")}</a>
        <a style='display:inline-block;margin:var(--space-2) 0' href='#g-next' data-goto='g-next'>${t("guide.next_title")}</a>
      </nav></div>
    <div class='panel' id='g-what'>${_back()}
      <b class='title'>${t("guide.what_title")}</b>
      <p>${t("guide.what_lead")}<b>${t("guide.what_core")}</b>${t("guide.what_tail")}</p></div>
    <div class='panel' id='g-steps'>${_back()}
      <b class='title'>${t("guide.steps_title")}</b>
      <div class='guide-flow'>
        <div class='guide-step'><span class='n'>1</span><b>${t("guide.step1_t")}</b><div>${t("guide.step1_d")}</div></div>
        <div class='guide-step'><span class='n'>2</span><b>${t("guide.step2_t")}</b><div>${t("guide.step2_d")}</div></div>
        <div class='guide-step'><span class='n'>3</span><b>${t("guide.step3_t")}</b><div>${t("guide.step3_d")}</div></div>
        <div class='guide-step'><span class='n'>4</span><b>${t("guide.step4_t")}</b><div>${t("guide.step4_d")}</div></div>
      </div></div>
    <div class='panel' id='g-wf'>${_back()}
      <b class='title'>${t("guide.wf_title")}</b>
      <p>${t("guide.wf_lead")}</p></div>
    <div class='panel' id='g-wf1'>${_back()}
      <b class='title'>${t("guide.wf1_t")}</b>
      <p>${t("guide.wf1_p0")}</p>
      <ul>
        <li>${t("guide.wf1_li1")}</li>
        <li>${t("guide.wf1_li2")}</li>
        <li>${t("guide.wf1_li3")}</li>
      </ul>
      <p class='muted'>${t("guide.wf1_out")}</p></div>
    <div class='panel' id='g-wf2'>${_back()}
      <b class='title'>${t("guide.wf2_t")}</b>
      <p>${t("guide.wf2_p0")}</p>
      <table class="glossary"><thead><tr>
        <th scope="col">${t("guide.wf2_th_ch")}</th>
        <th scope="col">${t("guide.wf2_th_what")}</th>
        <th scope="col">${t("guide.wf2_th_when")}</th>
      </tr></thead><tbody>
        <tr><td>${t("guide.wf2_ch_fake_t")}</td><td>${t("guide.wf2_ch_fake_d")}</td><td>${t("guide.wf2_ch_fake_when")}</td></tr>
        <tr><td>${t("guide.wf2_ch_openems_t")}</td><td>${t("guide.wf2_ch_openems_d")}</td><td>${t("guide.wf2_ch_openems_when")}</td></tr>
        <tr><td>${t("guide.wf2_ch_hfss_t")}</td><td>${t("guide.wf2_ch_hfss_d")}</td><td>${t("guide.wf2_ch_hfss_when")}</td></tr>
      </tbody></table>
      <p>${t("guide.wf2_li")}</p>
      <p class='muted'>${t("guide.wf2_hint")}</p></div>
    <div class='panel' id='g-wf3'>${_back()}
      <b class='title'>${t("guide.wf3_t")}</b>
      <p>${t("guide.wf3_fields_lead")}</p>
      <ul>
        <li><b>${t("guide.wf3_f1_t")}</b>${t("guide.wf3_f1_d")}</li>
        <li><b>${t("guide.wf3_f2_t")}</b>${t("guide.wf3_f2_d")}</li>
        <li><b>${t("guide.wf3_f3_t")}</b>${t("guide.wf3_f3_d")}</li>
        <li><b>${t("guide.wf3_f4_t")}</b>${t("guide.wf3_f4_d")}</li>
      </ul>
      <p>${t("guide.wf3_next")}</p>
      <p><b>${t("guide.wf3_q")}</b>${t("guide.wf3_a")}</p></div>
    <div class='panel' id='g-wf4'>${_back()}
      <b class='title'>${t("guide.wf4_t")}</b>
      <ul>
        <li><b>${t("guide.wf4_sweep_t")}</b>${t("guide.wf4_sweep_d")}</li>
        <li><b>${t("guide.wf4_mf_t")}</b>${t("guide.wf4_mf_d")}</li>
        <li><b>${t("guide.wf4_remote_t")}</b>${t("guide.wf4_remote_d")}</li>
      </ul></div>
    <div class='panel' id='g-gloss'>${_back()}
      <b class='title'>${t("guide.gl_title")}</b>
      <table class="glossary"><tbody>
        <tr><td>${t("guide.gl_recipe_t")}</td><td>${t("guide.gl_recipe_d")}</td></tr>
        <tr><td>Run</td><td>${t("guide.gl_run_d")}</td></tr>
        <tr><td>adapter</td><td>${t("guide.gl_adapter_d")}</td></tr>
        <tr><td>objectives</td><td>${t("guide.gl_obj_d")}</td></tr>
        <tr><td>${t("guide.gl_mf_t")}</td><td>${t("guide.gl_mf_d")}</td></tr>
        <tr><td>${t("guide.gl_p0_t")}</td><td>${t("guide.gl_p0_d")}</td></tr>
        <tr><td>${t("guide.gl_gate_t")}</td><td>${t("guide.gl_gate_d")}</td></tr>
      </tbody></table></div>
    <div class='panel' id='g-faq'>${_back()}
      <b class='title'>${t("guide.faq_title")}</b>
      <li><b>${t("guide.faq1_q")}</b>${t("guide.faq1_a")}</li>
      <li><b>${t("guide.faq2_q")}</b>${t("guide.faq2_a")}</li>
      <li><b>${t("guide.faq3_q")}</b>${t("guide.faq3_a")}</li>
      <li><b>${t("guide.faq4_q")}</b>${t("guide.faq4_a")}</li>
      </div>
    <div class='panel' id='g-next'>${_back()}
      <b class='title'>${t("guide.next_title")}</b>
      <li>${t("guide.next_1_lead")}<span class="muted">docs/rf_template_references.md</span>${t("guide.next_1_tail")}</li>
      <li>${t("guide.next_2")}</li></div>`;
  _bindToc(v);
  applyI18nRoot(v); // 壳首扫（本页全 t() 烘焙零 data-i18n；幂等空扫，接线口径与九页一致）
}
