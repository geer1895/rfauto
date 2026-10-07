// W1-E D-05 反证测试内核（node ES module，由 test_w1e_d05_sanitize.py 以
// subprocess 驱动）：禁用 DOMPurify 的各形态下，renderMarkdown 必须
// textContent 兜底——攻击者内容永不进入 innerHTML（零注入）。
//
// 手段注记（criteria §W1-E D-05 判据"js 逻辑单测"）：pages.js 是零依赖
// ES module（实测 node 可直 import，无顶层 DOM 访问），故内核行为用真
// 单测驱动；模板拼接语境的两个调用点（mdReady 分流）不可脱离整页 DOM，
// 由 python 侧静态断言钉（见 test_w1e_d05_sanitize.py::TestCallSiteDiscipline）。

const PAYLOAD = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

// pages.js 相对本测试文件：tests/unit/js/ → 仓根 src/rfauto/ui/static/
const PAGES_JS_URL = new URL(
  "../../../src/rfauto/ui/static/pages.js", import.meta.url).href;

function makeEl() {
  return { innerHTML: "", textContent: "" };
}

let failed = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`PASS ${name}`);
  } else {
    failed += 1;
    console.log(`FAIL ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

// ── 形态 1：DOMPurify 整体缺失（purify.min.js 未加载/加载顺序被破坏）──
{
  globalThis.window = {}; // window.DOMPurify === undefined
  const { renderMarkdown } = await import(PAGES_JS_URL);
  const el = makeEl();
  const ok = renderMarkdown(el, PAYLOAD);
  check("missing-purify: 渲染拒绝（返回 false）", ok === false);
  check("missing-purify: innerHTML 零注入（保持空串）",
    el.innerHTML === "", JSON.stringify(el.innerHTML));
  check("missing-purify: 内容以纯文本兜底可见",
    el.textContent === PAYLOAD,
    JSON.stringify(el.textContent));
}

// ── 形态 2：DOMPurify 存在但 sanitize 非函数（残缺对象）──
{
  globalThis.window = { DOMPurify: { sanitize: null } };
  const { renderMarkdown } = await import(PAGES_JS_URL);
  const el = makeEl();
  const ok = renderMarkdown(el, PAYLOAD);
  check("broken-purify: 渲染拒绝", ok === false);
  check("broken-purify: innerHTML 零注入", el.innerHTML === "");
  check("broken-purify: textContent 兜底", el.textContent === PAYLOAD);
}

// ── 形态 3：sanitize 返回非字符串（净化失败形态）──
{
  globalThis.window = { DOMPurify: { sanitize: () => undefined } };
  const { renderMarkdown } = await import(PAGES_JS_URL);
  const el = makeEl();
  const ok = renderMarkdown(el, PAYLOAD);
  check("nonstring-clean: 渲染拒绝", ok === false);
  check("nonstring-clean: innerHTML 零注入", el.innerHTML === "");
}

// ── 形态 4：净化链健康 → 照常 innerHTML（成功路径零变化）──
{
  const SANITIZED = "<p>safe</p>";
  globalThis.window = { DOMPurify: { sanitize: () => SANITIZED } };
  const { renderMarkdown } = await import(PAGES_JS_URL);
  const el = makeEl();
  const ok = renderMarkdown(el, PAYLOAD);
  check("healthy: 走净化 innerHTML（返回 true）", ok === true);
  check("healthy: innerHTML=净化结果", el.innerHTML === SANITIZED);
  check("healthy: textContent 未被误写", el.textContent === "");
}

if (failed) {
  console.log(`FAILED ${failed}`);
  process.exit(1);
}
console.log("ALL_OK");
