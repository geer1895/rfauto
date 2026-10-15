/* rfauto 工作台 DOM 工具单源（aurora_d UI-R2 自 pages.js 拆出）：
   esc/escAttr HTML 转义单源（AU-4 五字符集，62 sink 纪律的地基）、
   fmtNum 数值展示单源、markdown 净化单点（D-05 硬错化：DOMPurify
   缺失即拒绝 innerHTML）、help 本页说明壳、downloadTextFile Blob 下载
   （plotCard 复用包装/导出工具条共用）。零顶层 DOM 执行（node 可 import）。 */

/* AU-4 XSS 清扫批：HTML 转义单源。API/用户数据插值进 innerHTML 模板时，
   文本语境用 esc()、属性语境用 escAttr()（引号内属性值）。二者转义同一
   五字符集（& < > " '），入参先 String() 再替换——对不含特殊字符的正常
   数据逐字节不变（渲染不变铁律）；含特殊字符时只产生实体，不再能闭合
   标签/属性。属性语境统一走 escAttr 以便审计区分语境。 */
const _ESC_RE = /[&<>"']/g;
const _ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export function esc(v) {
  return String(v).replace(_ESC_RE, (c) => _ESC_MAP[c]);
}
export function escAttr(v) {
  return esc(v);
}

/* aurora36 W3-B（R1 P1-10 数字口径）：数值展示单源——null/undefined/NaN →
   "-"，其余 toFixed(d)。约定沿用既有逐处口径（cost=4dp、S11=2dB、ρ=3dp），
   只在明显不一致处替换（campaign 表 cost 原用 8 位有效数字的 toPrecision
   是全仓唯一离群点，反直觉）；既有一致口径逐处不动（最小替换原则）。 */
export function fmtNum(v, d = 4) {
  const n = +v;
  return (v === null || v === undefined || Number.isNaN(n)) ? "-" : n.toFixed(d);
}

/* UI-R11（A6 P2-3 收口）：失败信封错误文案单源——契约 §3 兼容读法，与
   cli/domains/anchors.py 的 _error_text 同款语义（按序回退：errors 列表
   join "; " → error → reason → 兜底文案）。error_envelope 只带 errors
   列表（单数 error 键已废）；历史遗留形态（fs_list/playground 等单数
   error）与 api() 网络兜底形状（{ok, error, errors}）都经此链可达——
   裸读 d.error 在 errors 列表信封下渲染 "undefined"（filebrowser 实证）。 */
export function errorText(d, fallback = "未知错误") {
  const errs = d && d.errors;
  if (Array.isArray(errs) && errs.length)
    return errs.map((e) => String(e)).join("; ");
  return String((d && (d.error || d.reason)) || fallback);
}
// S-2 XSS 主向量（code_audit_slice6）：marked.parse 的输出一律经 DOMPurify
// 白名单净化后才可入 innerHTML（vendor/purify.min.js，index.html 在 marked
// 之后引入）。
// D-05 硬错化（2026-10-05 W1-E）：净化器缺失（异常环境/加载顺序被破坏）或
// 净化结果非字符串 → mdSanitize 返回 null，调用方**拒绝走 innerHTML**，
// 经 renderMarkdown 单点封装降级 textContent（模板拼接语境降级 esc() 转义
// 文本，二者同保证：攻击者内容永不作为 HTML 解释）。旧"裸 <script> 剥离"
// 弱降级已删除——它挡不住 <img onerror=…>/<svg onload=…>/<iframe src=…>
// 等向量，等于净化缺失时假装安全（物理红永不静默同源原则）。
export function mdSanitize(html) {
  const P = window.DOMPurify;
  if (!P || typeof P.sanitize !== "function") return null;
  const clean = P.sanitize(html);
  return typeof clean === "string" ? clean : null;
}

// D-05：净化链可用性探针（mdSanitize 同判据，供模板拼接语境先行分流——
// 不可用时走 esc() 纯文本分支而不是把 null 拼进 innerHTML）。
export function mdReady() {
  const P = window.DOMPurify;
  return !!(P && typeof P.sanitize === "function");
}

// D-05：markdown 渲染单点。净化不可用/失败 → textContent 兜底（返回
// false 供调用方按需降级样式），内容只作为纯文本显示，零 HTML 注入面。
export function renderMarkdown(el, rawHtml) {
  const clean = mdSanitize(rawHtml);
  if (clean === null) {
    el.textContent = String(rawHtml);
    return false;
  }
  el.innerHTML = clean;
  return true;
}
/* 本页说明组件（每页顶部可折叠帮助，降低上手门槛） */
export function help(text) {
  return `<details class="help"><summary>❓ 本页说明（点开查看）</summary>${text}</details>`;
}
/* 与 plotcard.js downloadFile 同构（彼处未导出；W2-C 接口诉求落地后删除）。 */
export function downloadTextFile(name, content, mime) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
