/* rfauto 文件浏览器弹层（aurora_d UI-R2 自 pages.js 拆出，逐字节
   搬移）：工程导入选 .aedt/.yaml 与 S 参数页外部 .sNp 叠加共用
   （/api/fs/list）。 */

import { T } from "./context.js";
import { errorText, esc, escAttr } from "./dom.js";
import { bindClickRows, kitClickRowAttrs } from "./kit.js";

/* 文件浏览器（弹层）：选 .aedt/.yaml 文件或目录 */
export function fileBrowser(startPath, onPick) {
  let old = document.getElementById("fs-browser");
  if (old) old.remove();
  const modal = document.createElement("div");
  modal.id = "fs-browser";
  modal.setAttribute("role", "dialog"); // PR-1 a11y：模态弹层语义
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", "选择文件或目录");
  // UI-R12 任务3：遮罩底走 ：root 令牌 --backdrop-dim（同值单源收编，
  // 原内联字面量退役——字面量不再留在本文件，防第二源回潮）
  modal.style.cssText = "position:fixed;inset:0;background:var(--backdrop-dim);z-index:var(--z-modal);display:flex;align-items:center;justify-content:center";
  modal.innerHTML = `<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;width:640px;max-width:94vw;max-height:80vh;display:flex;flex-direction:column;padding:14px">
    <div class="toolbar"><b>选择文件 / 目录</b>
      <input id="fs-path" style="flex:1" placeholder="工作区目录或其子目录" aria-label="路径">
      <button class="minor" id="fs-go">跳转</button>
      <button class="minor" id="fs-close">关闭</button></div>
    <div id="fs-list" class="muted" style="overflow:auto;flex:1;min-height:260px">加载中...</div></div>`;
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
    const d = await T.api("/api/fs/list?path=" + encodeURIComponent(path || ""));
    const el = modal.querySelector("#fs-list");
    // UI-R11（A6 P2-3）：失败文案走 errorText 兼容读法（errors→error→reason
    // 回退链）——error_envelope 只有 errors 列表，裸读单数 error 键会渲染出
    // 字面 "undefined"
    if (!d.ok) { el.textContent = errorText(d); return; }
    modal.querySelector("#fs-path").value = d.path;
    // UI-R4：行键盘可达（div 行 role=button 缺省；aria-label 行动作——
    // 名称/路径经 kit escAttr 出口转义）
    let html = d.parent ? `<div class="fs-row" data-p="${escAttr(d.parent)}" ${kitClickRowAttrs({ label: "返回上级目录" })} style="cursor:pointer">📁 ..（上级）</div>` : "";
    for (const e of d.entries) {
      const icon = e.kind === "dir" ? "📁" : (e.name.endsWith(".aedt") ? "📡" : "📄");
      const lbl = e.kind === "dir" ? "打开目录 " + e.name : "选择 " + e.name;
      html += `<div class="fs-row" data-p="${escAttr(e.path)}" data-k="${escAttr(e.kind)}" ${kitClickRowAttrs({ label: lbl })} style="cursor:pointer;padding:3px 4px">${icon} ${esc(e.name)}</div>`;
    }
    el.innerHTML = html || "<span class='muted'>空目录</span>";
    // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源）
    bindClickRows(el, (row) => {
      if (row.dataset.k === "dir") load(row.dataset.p);
      else { onPick(row.dataset.p); close(); }
    }, ".fs-row");
  }
  modal.querySelector("#fs-go").onclick = () => load(modal.querySelector("#fs-path").value.trim());
  load(startPath);
}
