/* rfauto 文件浏览器弹层（aurora_d UI-R2 自 pages.js 拆出，逐字节
   搬移）：工程导入选 .aedt/.yaml 与 S 参数页外部 .sNp 叠加共用
   （/api/fs/list）。
   P3-4（aurora_n wave_ui_c）：场景化扩展名过滤（纯前端）——fileBrowser
   第三形参 exts（如 ['.aedt'] / ['.s1p',…'.s8p']）只对文件条目生效（目录
   与「上级」恒可见，导航不断）；工具条加「仅显示 …」徽章（过滤语义用户
   可感知）+ 全被滤掉时给一行说明。审计原案"后端 list API 加 param"不采
   （服务端语义零变化红线），过滤在渲染层做，/api/fs/list 契约不动。 */

import { T } from "./context.js";
import { errorText, esc, escAttr } from "./dom.js";
import { bindClickRows, kitClickRowAttrs } from "./kit.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本模块 1 点）
// ——非视图共享模块（sparams/import 等视图共用的文件弹层）：无视图作用域可
// 绑，不接 viewSignal（模态打开期遮罩挡导航，无"切页在途写隐藏区"面，视图
// 作用域取消对其不适用）；信封消费形态逐键不变（errorText 回退链原样）。
import { apiFetch } from "./api.js";
// P3-4：过滤徽章/空态文案走词表（i18n 棘轮：本文件不再新增硬编码中文）。
// aurora_o i18n 分波席：弹层 chrome 全量迁词表（fs.* 域 12 键，zh 逐字节
// 同笔 en 新增）——字面量中文清零（硬编码棘轮本文件 49→0）。
import { t } from "./i18n.js";

/* P3-4 过滤单源（纯函数，node 行为钉消费）：exts=null/空=不过滤（原样）；
   目录条目恒保留；其余按扩展名后缀（大小写不敏感）保留。 */
export function fsFilterEntries(entries, exts) {
  const list = Array.isArray(entries) ? entries : [];
  if (!Array.isArray(exts) || !exts.length) return list;
  const ex = exts.map((e) => String(e).toLowerCase());
  return list.filter((e) => !e || e.kind === "dir" ||
    ex.some((x) => String(e.name || "").toLowerCase().endsWith(x)));
}

/* 文件浏览器（弹层）：选 .aedt/.yaml 文件或目录 */
export function fileBrowser(startPath, onPick, exts) {
  const _exts = Array.isArray(exts)
    ? exts.map((e) => String(e).toLowerCase()).filter((e) => e.startsWith("."))
    : null;
  let old = document.getElementById("fs-browser");
  if (old) old.remove();
  const modal = document.createElement("div");
  modal.id = "fs-browser";
  modal.setAttribute("role", "dialog"); // PR-1 a11y：模态弹层语义
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", t("fs.aria_dialog"));
  // UI-R12 任务3：遮罩底走 ：root 令牌 --backdrop-dim（同值单源收编，
  // 原内联字面量退役——字面量不再留在本文件，防第二源回潮）
  modal.style.cssText = "position:fixed;inset:0;background:var(--backdrop-dim);z-index:var(--z-modal);display:flex;align-items:center;justify-content:center";
  modal.innerHTML = `<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;width:640px;max-width:94vw;max-height:80vh;display:flex;flex-direction:column;padding:14px">
    <div class="toolbar"><b>${esc(t("fs.title"))}</b>` +
    (_exts ? ` <span class="badge muted">${esc(t("fs.filter_badge_tpl", { list: _exts.join(" / ") }))}</span>` : "") +
    `
      <input id="fs-path" style="flex:1" placeholder="${escAttr(t("fs.path_ph"))}" aria-label="${escAttr(t("fs.path_aria"))}">
      <button class="minor" id="fs-go">${esc(t("fs.go"))}</button>
      <button class="minor" id="fs-close">${esc(t("fs.close"))}</button></div>
    <div id="fs-list" class="muted" style="overflow:auto;flex:1;min-height:260px">${esc(t("fs.loading"))}</div></div>`;
  document.body.appendChild(modal);
  // UI-R4 焦点陷阱三件套（W2-C 灯箱/命令面板同款模式）：①打开前焦点存根
  // ②Tab 首尾回绕困在弹层内 + Esc 关闭 ③关闭还焦触发元素。
  const savedFocus = document.activeElement; // 焦点陷阱①：打开前的 activeElement
  const close = () => {
    modal.remove();
    if (savedFocus && document.contains(savedFocus) &&
        typeof savedFocus.focus === "function")
      savedFocus.focus(); // 焦点陷阱③：关闭还焦
  };
  modal.querySelector("#fs-close").onclick = close;
  modal.onclick = (e) => { if (e.target === modal) close(); };
  modal.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") {
      // 焦点陷阱②：Tab 首尾回绕（弹层内可聚焦元素循环，不逃出模态）
      const focusables = [...modal.querySelectorAll(
          "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
        .filter((el) => el.offsetParent !== null);
      e.preventDefault();
      if (!focusables.length) return;
      const idx = focusables.indexOf(document.activeElement);
      const next = idx === -1
        ? (e.shiftKey ? focusables[focusables.length - 1] : focusables[0])
        : (e.shiftKey
          ? focusables[(idx - 1 + focusables.length) % focusables.length]
          : focusables[(idx + 1) % focusables.length]);
      next.focus();
    }
  });
  // 初始焦点落路径输入（弹层主动作=输入路径跳转；行清单加载后 Tab 可达）
  const pathInput = modal.querySelector("#fs-path");
  if (pathInput) pathInput.focus({ preventScroll: true });

  async function load(path) {
    const d = await apiFetch("/api/fs/list?path=" + encodeURIComponent(path || ""));
    const el = modal.querySelector("#fs-list");
    // UI-R11（A6 P2-3）：失败文案走 errorText 兼容读法（errors→error→reason
    // 回退链）——error_envelope 只有 errors 列表，裸读单数 error 键会渲染出
    // 字面 "undefined"
    if (!d.ok) { el.textContent = errorText(d); return; }
    modal.querySelector("#fs-path").value = d.path;
    // UI-R4：行键盘可达（div 行 role=button 缺省；aria-label 行动作——
    // 名称/路径经 kit escAttr 出口转义）
    // 「..（上级）」行必须带 data-k="dir"：bindClickRows 按 dataset.k 分派
    // （dir→进入 / 其余→onPick 选中关闭）——缺 data-k 时点上级会被当文件
    // 选中提交（用户实测"上级点不了"2026-10-29），非导航。
    let html = d.parent ? `<div class="fs-row" data-p="${escAttr(d.parent)}" data-k="dir" ${kitClickRowAttrs({ label: t("fs.parent_label") })} style="cursor:pointer">${esc(t("fs.parent_row"))}</div>` : "";
    const all = d.entries || [];
    const entries = fsFilterEntries(all, _exts); // P3-4：场景化扩展名过滤（目录恒可见）
    for (const e of entries) {
      const icon = e.kind === "dir" ? "📁" : (e.name.endsWith(".aedt") ? "📡" : "📄");
      const lbl = e.kind === "dir"
        ? t("fs.open_dir_lbl") + e.name : t("fs.pick_lbl") + e.name;
      html += `<div class="fs-row" data-p="${escAttr(e.path)}" data-k="${escAttr(e.kind)}" ${kitClickRowAttrs({ label: lbl })} style="cursor:pointer;padding:3px 4px">${icon} ${esc(e.name)}</div>`;
    }
    el.innerHTML = html || `<span class='muted'>${esc(t("fs.empty_dir"))}</span>`;
    // P3-4：过滤语义可感知收尾——目录里有条目但全被过滤时补一行说明
    //（与"空目录"原样区分：前者是过滤所致，后者是真空）。
    if (!entries.length && all.length)
      el.insertAdjacentHTML("beforeend",
        `<div class="muted">${t("fs.filter_empty")}</div>`);
    // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源）
    bindClickRows(el, (row) => {
      if (row.dataset.k === "dir") load(row.dataset.p);
      else { onPick(row.dataset.p); close(); }
    }, ".fs-row");
  }
  modal.querySelector("#fs-go").onclick = () => load(modal.querySelector("#fs-path").value.trim());
  load(startPath);
}
