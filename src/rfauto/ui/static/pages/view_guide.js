/* rfauto 使用指南页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）。
   i18n（架构批 W2-S1 批 4，R1 §面2 P9-5）：纯静态页整页分段 t() 迁入
   （guide.* 41 键，zh 与旧字面逐字节同、en 新增）——本页零 API 数据、
   零动态容器，结构（<li>/<b>/<table>/guide-flow）留模板、纯文本段进词表
   （view_dashboard help 块分段先例）；值内 &lt;/&gt; 为渲染保真的字符实体
   （深链示例/S11<-15dB），非标签。 */

import { T } from "./context.js";
import { help } from "./dom.js";
import { t, applyI18nRoot } from "./i18n.js";

/* ═══ 使用指南 ═══ */
export function pageGuide() {
  const v = T.$("view-guide");
  v.innerHTML = help(`
    <li>${t("guide.help_1")}</li>
    <li>${t("guide.help_2")}</li>`) +
    `<h2 class='page'>${t("guide.title")} <small>${t("guide.subtitle")}</small></h2>
    <div class='panel'><b class='title'>${t("guide.what_title")}</b>
      <p>${t("guide.what_lead")}<b>${t("guide.what_core")}</b>${t("guide.what_tail")}</p></div>
    <div class='panel'><b class='title'>${t("guide.steps_title")}</b>
      <div class='guide-flow'>
        <div class='guide-step'><span class='n'>1</span><b>${t("guide.step1_t")}</b><div>${t("guide.step1_d")}</div></div>
        <div class='guide-step'><span class='n'>2</span><b>${t("guide.step2_t")}</b><div>${t("guide.step2_d")}</div></div>
        <div class='guide-step'><span class='n'>3</span><b>${t("guide.step3_t")}</b><div>${t("guide.step3_d")}</div></div>
        <div class='guide-step'><span class='n'>4</span><b>${t("guide.step4_t")}</b><div>${t("guide.step4_d")}</div></div>
      </div></div>
    <div class='panel'><b class='title'>${t("guide.gl_title")}</b>
      <table class="glossary"><tbody>
        <tr><td>${t("guide.gl_recipe_t")}</td><td>${t("guide.gl_recipe_d")}</td></tr>
        <tr><td>Run</td><td>${t("guide.gl_run_d")}</td></tr>
        <tr><td>adapter</td><td>${t("guide.gl_adapter_d")}</td></tr>
        <tr><td>objectives</td><td>${t("guide.gl_obj_d")}</td></tr>
        <tr><td>${t("guide.gl_mf_t")}</td><td>${t("guide.gl_mf_d")}</td></tr>
        <tr><td>P0 gate</td><td>${t("guide.gl_p0_d")}</td></tr>
        <tr><td>${t("guide.gl_gate_t")}</td><td>${t("guide.gl_gate_d")}</td></tr>
      </tbody></table></div>
    <div class='panel'><b class='title'>${t("guide.faq_title")}</b>
      <li><b>${t("guide.faq1_q")}</b>${t("guide.faq1_a")}</li>
      <li><b>${t("guide.faq2_q")}</b>${t("guide.faq2_a")}</li>
      <li><b>${t("guide.faq3_q")}</b>${t("guide.faq3_a")}</li>
      <li><b>${t("guide.faq4_q")}</b>${t("guide.faq4_a")}</li>
      </div>
    <div class='panel'><b class='title'>${t("guide.next_title")}</b>
      <li>${t("guide.next_1_lead")}<span class="muted">docs/rf_template_references.md</span>${t("guide.next_1_tail")}</li>
      <li>${t("guide.next_2")}</li></div>`;
  applyI18nRoot(v); // 壳首扫（本页全 t() 烘焙零 data-i18n；幂等空扫，接线口径与九页一致）
}
