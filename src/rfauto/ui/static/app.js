/* rfauto 射频调优工作台前端（vanilla JS + three.js，无构建步骤）。
   本文件 = 外壳（导航/工具函数/3D）；各页面逻辑在 pages.js。
   P8-2（aurora_f W3-S9，R1 §面1 重审）：three 不再顶层静态 import——
   drawBoxes 是全壳唯一静态消费点（T.THREE 消费点 view_fieldviz drawIsoMesh
   同批改调用点动态 import），改为 3D 渲染时 `await import("three")`
   （importmap 单源映射 index.html，模块缓存命中后零开销）。首屏关键路径
   去 1,272,972B 原始 / 256,743B gzip（W1 GZip 后实=首屏线传 36% 单件），
   仅 recipe/detail/field 三视图首次 3D 渲染时拉取。旧否决理由（monolith
   时代 pages.js 同步消费 T.THREE）已失效，见 runs/aurora_f/R1_ui_v8_audit.md
   P8-2 与本席位报告。 */
import { initPages, showPage, esc } from "./pages.js";
// aurora72 A4-C（R6 审计 R-2）：parseRoute（两级 hash 解析纯函数）与
// routeOpen（参数页 opener 注册表分发）单源在 pages.js——本壳只持策略面。
// （独立 import 声明：上行形态被 test_ui_xss_escape 源码钉逐字，勿合并。）
import { parseRoute, routeOpen } from "./pages.js";
// PR-3 PlotCard：option 构造单源在 plotcard.js（buildEChartOption 与
// 迁移前 drawEChart 逐字节等价，golden 快照钉 runs/pr34/），drawEChart
// 与 plotCard 共用；drawLineChart/Smith/3D 自研管线不动。
import { buildEChartOption, plotCard } from "./plotcard.js";
// aurora72 A5-B（R6 审计 R-4）：主题判定/双档调色板单源在 theme.js——
// body.light 现取 bodyIsLight()、CHART_COLORS 档位经 chartPalette(light)、
// 自研 canvas 管线双档色经 themePick(light, THEME_COLORS.x)（SCENE3D 两档
// 3D 场景色暂留本壳：test_ui_nav_focus 源码钉逐字钉住其消费位，A5-B 不动）。
import {
  bodyIsLight, CANVAS_FONT, CANVAS_LINE_LAYOUT, chartPalette, themePick, THEME_COLORS,
} from "./theme.js";
// UI-R12（aurora_d 前端深化席）：统一 API 请求层单源在 pages/api.js——
// 本壳 api（T.api 载体）保形消费 apiRequestInit（token/init 归一单源，
// 无 token 无 opts 时逐字节等价），activate 消费 abortViewSignals 做
// 切页在途请求收束（仅影响显式接 viewSignal 的迁移视图）。
import { apiRequestInit, abortViewSignals, setApiNotifier } from "./pages/api.js";
// W14-S2（R1 P9-12 离线检测）：断网/恢复提示串走词表单源（common.offline/
// online——i18n L0 零依赖，app 壳直连与 palette 同款口径）；当前页名经
// context 访问器读（_activeView 写面仍在 router.showPage 单源）。
import { t } from "./pages/i18n.js";
import { getActiveView } from "./pages/context.js";
// W14-S2：online 恢复后当前页局部刷新走 PAGE_CTX 钩子单源（facade re-export）
import { pageContextFor } from "./pages.js";

const $ = (id) => document.getElementById(id);
/* W2-C 全局兜错（R1 审计 P1-5）：网络断/服务器 5xx 非 JSON 时 fetch 或
   r.json() 会抛错——此前未捕获 → unhandled rejection + 页面停在"加载中"
   静默空白。兜底形状 {ok:false, error, errors} 与 pages.js 两种消费判法
   对齐：`if (!d.ok)` 分支读 d.error 或 (d.errors||[]).join("; ")；无 .ok
   分支的聚合页（dashboard）用 `d.runs || []` 兜底，undefined 字段安全。
   msg 已存在于本文件——失败必须可见，不只返回形状。 */
export const api = async (url, opts) => {
  try {
    const r = await fetch(url, apiRequestInit(opts)); // UI-R12：init 归一单源（token 透传；缺省零变化）
    return await r.json(); // await 留在 try 内：json 解析失败同样入 catch
  } catch {
    const m = "请求失败（网络或服务器异常）";
    try { msg(m, false); } catch { /* msg 载体缺席（异常部署）时静默 */ }
    return { ok: false, error: m, errors: [m] };
  }
};
export const $id = $;
/* W8-B P1-2（2026-10-12）：err 消息此前无撤销路径——一次 500 的残影横跨
   页面滞留数分钟误导当前状态。错误 toast 8s 后自动清除（阅读时长取 ok 的
   两倍），成功仍 4s；单定时器句柄：新消息先清旧定时器，否则 ok 的 4s
   撤销会把后到的 err 提前清掉。
   R3 人性化三批（hfssq-ui-kit P7）：退场 slide+fade——到时先挂 .msg-out
   （CSS toast-out 滑出动画，150ms）再复位 hidden；双句柄（到时器+退场
   收束器）新消息先全清，防"退场中残影被新消息顶掉后旧收束器误隐新 toast"。
   复位→重显之间强制一次样式失效（reflow），display none→block 真实切换
   才能重放滑入动画（同类名直切浏览器不重启 animation）。 */
let _msgTimer = null;
let _msgOutTimer = null;
export function msg(text, ok) {
  const el = $("msg");
  if (_msgTimer) clearTimeout(_msgTimer);
  if (_msgOutTimer) clearTimeout(_msgOutTimer);
  _msgOutTimer = null;
  el.textContent = text;
  el.className = "msg";
  void el.offsetWidth; // 强制样式失效：退场中断/同帧重显都能重放滑入动画
  el.className = "msg " + (ok ? "ok" : "err");
  _msgTimer = setTimeout(() => {
    _msgTimer = null;
    el.className = "msg msg-out " + (ok ? "ok" : "err"); // 退场滑出（CSS 单源）
    _msgOutTimer = setTimeout(() => {
      _msgOutTimer = null;
      el.className = "msg";
    }, 200);
  }, ok ? 4000 : 8000);
}

/* W2-C 切页公告（R1 审计 P1-1）：视觉隐藏的 aria-live region（自建节点，
   不动 index.html）。不用 #msg——页名公告是常态导航反馈，走 #msg 会闪
   红/绿 toast。先清空再延迟写入：同页名重复切换也能触发读屏播报。
   公告是增强面，任何异常不得阻塞切页（#105 best-effort 纪律）。
   W5-S23：升格导出单源（轮询终态/状态变迁公告消费——view_tune/loopboard
   经 initPages 工具集 T.announce 调用；本文件仍是 live region 唯一属主）。 */
let _live = null;
export function announce(text) {
  try {
    if (!_live) {
      _live = document.createElement("div");
      _live.setAttribute("role", "status");
      _live.setAttribute("aria-live", "polite");
      _live.style.cssText =
        "position:absolute;width:1px;height:1px;margin:-1px;padding:0;" +
        "border:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;";
      document.body.appendChild(_live);
    }
    _live.textContent = "";
    setTimeout(() => { _live.textContent = text; }, 30);
  } catch { /* 读屏不可用时静默 */ }
}

/* ── 导航 ── */
const navBtns = [...document.querySelectorAll("#nav button")];
for (const b of navBtns) {
  b.onclick = () => showPage(b.dataset.v);
}
/* W2-C 跳过链接行为（R1 审计 P2-4）：锚点 <a class="skip-link"> 与目标
   id=main-content 的本体在 index.html（W2-A 席）；本壳只绑行为并把焦点
   真正落到主内容（main 默认不可聚焦，须补 tabindex=-1）。锚点缺席时
   静默不绑（零副作用），W2-A 落锚后即自动生效。 */
const _skip = document.querySelector("a.skip-link");
if (_skip) {
  _skip.addEventListener("click", (e) => {
    const target = document.getElementById("main-content") ||
      document.querySelector("main");
    if (!target) return;
    e.preventDefault();
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  });
}
function activate(v) {
  abortViewSignals(); // UI-R12：切页收束上一页在途请求（仅迁移视图的 viewSignal 受影响）
  for (const b of navBtns) {
    b.classList.toggle("active", b.dataset.v === v);
    // PR-1 a11y：当前页 aria-current（读屏可知导航位置）
    if (b.dataset.v === v) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
    if (b.dataset.v === "detail")
      b.style.display = v === "detail" ? "" : "none"; // 详情页仅从 run 点入时显示
  }
  for (const s of document.querySelectorAll("main > section"))
    s.style.display = s.id === "view-" + v ? "" : "none";
  /* W2-C 切页焦点管理（R1 审计 P1-1）：切页后键盘/读屏焦点随页走——新页
     h2.page 动态补 tabindex=-1 聚焦（页标题单源在 pages.js 各渲染器，
     本壳不维护第二份清单），并公告页名。setTimeout(0)：showPage 在
     activate 之后才同步渲染视图 innerHTML，宏任务时标题已落在 DOM。 */
  setTimeout(() => {
    const h = document.querySelector('#view-' + v + ' h2.page');
    if (!h) { _lazyFocus.pending = v; return; } // UI-R12：懒加载模块在途→渲染后补焦
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
    announce(h.textContent.replace(/\s+/g, " ").trim());
  }, 0);
}

/* UI-R12 懒加载补焦桥：视图模块动态 import 在途时上方 setTimeout(0) 找不到
   h2.page——挂起页键于 _lazyFocus（对象经工具集注入后与 pages.js 共享同一
   引用），渲染完成后由 pages.js _lazyView 包装器调 pageFocusAfterRender
   补焦+公告（与上方 timeout 同一套面板；模块缓存命中路径不触发，行为与
   旧一致）。 */
const _lazyFocus = { pending: null };
function pageFocusAfterRender(v) {
  const h = document.querySelector('#view-' + v + ' h2.page');
  if (!h) return false;
  if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
  h.focus({ preventScroll: true });
  announce(h.textContent.replace(/\s+/g, " ").trim());
  _lazyFocus.pending = null;
  return true;
}

/* 通用小部件：徽章（text 一律 esc 转义后再插值——AU-4：badge 是 API 数据
   的 HTML 出口之一（如 run status/anchor 状态），单点转义覆盖全部调用面） */
export const badge = (text, cls) => `<span class="badge ${cls}">${esc(text)}</span>`;
export const passBadge = (p) =>
  p === true ? badge("PASS", "ok") : p === false ? badge("FAIL", "err") : badge("N/A", "muted");

/* PR-1 对比度：图表系列调色板按主题分档——单源已收编 theme.js（aurora72
   A5-B，R6 审计 R-4），本壳经 chartPalette(light) 消费（dark/light 档取值、
   ocean 共用 dark 档的已固化结论与对比度核算见 theme.js 头注与
   runs/pr1_contrast/）。显式 s.color 仍优先——调色板只兜底缺省系列。 */

/* 通用折线图（canvas，多曲线 + 主题自适应网格） */
export function drawLineChart(canvas, series, labels) {
  const ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth || 600;
  canvas.height = canvas.clientHeight || 260;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const light = bodyIsLight();
  const gridColor = themePick(light, THEME_COLORS.grid); // 网格线=装饰性（读数靠刻度文字）
  const readColor = themePick(light, THEME_COLORS.read); // 刻度文字：双主题对底 ≥4.5:1
  if (!series.length || !series[0].x.length) return;
  // PR-1 a11y：canvas 图像语义
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label",
    `折线图：${series.map((s) => s.name).filter(Boolean).join("、") || "数据系列"}`);
  // W3-S12（P-5）：边距/字号常量收 theme.js 单源（值冻结 46/14/14/26，渲染不变）
  const { left: L, right: R, top: T, bottom: B } = CANVAS_LINE_LAYOUT;
  const W = canvas.width, H = canvas.height;
  const xs = series.flatMap((s) => s.x), ys = series.flatMap((s) => s.y);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const px = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const py = (y) => H - B - ((y - ymin) / (ymax - ymin || 1)) * (H - T - B);
  ctx.strokeStyle = gridColor;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const gx = L + (i / 4) * (W - L - R), gy = T + (i / 4) * (H - T - B);
    ctx.moveTo(gx, T); ctx.lineTo(gx, H - B);
    ctx.moveTo(L, gy); ctx.lineTo(W - R, gy);
  }
  ctx.stroke();
  const colors = chartPalette(light);
  series.forEach((s, i) => {
    ctx.strokeStyle = s.color || colors[i % colors.length];
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    s.x.forEach((x, j) => (j ? ctx.lineTo(px(x), py(s.y[j])) : ctx.moveTo(px(x), py(s.y[j]))));
    ctx.stroke();
  });
  ctx.fillStyle = readColor;
  ctx.font = CANVAS_FONT; // W3-S12：字号单源（值冻结 "11px sans-serif"）
  ctx.fillText(xmin.toFixed(2), L, H - 8);
  ctx.fillText(xmax.toFixed(2), W - R - 40, H - 8);
  ctx.fillText(ymax.toFixed(1), 4, T + 8);
  ctx.fillText(ymin.toFixed(1), 4, H - B);
  if (labels) {
    ctx.textAlign = "right";
    series.forEach((s, i) => {
      ctx.fillStyle = s.color || colors[i % colors.length];
      ctx.fillText(s.name || labels[i] || "", W - R, T + 10 + i * 14);
    });
  }
}

/* 交互式图表（ECharts：缩放/悬停读数/图例开关），theme 自适应。
   PR-3：option 构造委托 plotcard.js 单源 builder（等价快照钉在
   tests/unit/test_ui_plotcard.py）；本壳保留容器语义（role/aria/height）
   与故障可见化。新调用面请用 plotCard（带导出/十字线/收敛模式）。 */
export function drawEChart(el, series, opts = {}) {
  try {
    const light = bodyIsLight();
    // PR-1 a11y：图表容器图像语义（系列名+轴标签进 aria-label；opts.ariaLabel 显式覆盖）
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", opts.ariaLabel ||
      `图表：${series.map((s) => s.name).filter(Boolean).join("、") || "数据系列"}` +
      `${opts.ylabel ? "，纵轴 " + opts.ylabel : ""}${opts.xlabel ? "，横轴 " + opts.xlabel : ""}`);
    el.innerHTML = "";
    el.style.height = opts.height || "280px";
    const chart = window.echarts.init(el);
    chart.setOption(buildEChartOption(series, opts, {
      light,
      palette: chartPalette(light),
    }));
    window.addEventListener("resize", () => chart.resize());
    return chart;
  } catch (e) {
    // 图表故障可见化——不静默吞错（排查 #135 教训）
    el.innerHTML = `<span style="color:var(--err)">chart error: ${esc(e.message)}</span>`;
    return null;
  }
}

/* PR-3 PlotCard 注入：主题态在本壳现取（与 drawEChart 同一判定时机），
   调色板单源 chartPalette（theme.js）传入 plotcard.js。 */
function uiPlotCard(el, props = {}) {
  const light = bodyIsLight();
  return plotCard(el, props, {
    light,
    palette: chartPalette(light),
  });
}

/* ── 灯箱 ── */
/* W2-C 弹层焦点三件套（R1 审计 P1-3）：打开时焦点入弹层、Tab 首尾回绕困
   在弹层内、Esc/遮罩点击关闭并还焦触发元素。与 palette.js 的命令面板是
   同一模式的两处实现（不抽共享模块：app.js 顶层跑 DOM 初始化——three 已
   改 3D 调用点动态 import（W3-S9），顶层 DOM 面仍在，palette 若 import
   本文件仍会连带炸掉 node 行为测试的 import 链）。 */
let _lbSavedFocus = null; // 焦点陷阱①：打开前的 activeElement

function lightboxClose() {
  const lb = $("lightbox");
  if (!lb.classList.contains("show")) return;
  lb.classList.remove("show");
  if (_lbSavedFocus && document.contains(_lbSavedFocus) &&
      typeof _lbSavedFocus.focus === "function")
    _lbSavedFocus.focus(); // 焦点陷阱③：关闭还焦
  _lbSavedFocus = null;
}

export function lightboxContent(node, cap) {
  const lb = $("lightbox");
  if (!_lbSavedFocus) _lbSavedFocus = document.activeElement;
  $("lightbox-cap").textContent = cap || "";
  lb.querySelectorAll("canvas,img").forEach((el) => el.remove());
  lb.insertBefore(node, lb.firstChild);
  lb.classList.add("show");
  // 焦点陷阱⓪：灯箱内常无可聚焦元素（图/说明文字），焦点落弹层本体
  if (!lb.hasAttribute("tabindex")) lb.setAttribute("tabindex", "-1");
  lb.focus({ preventScroll: true });
}
export function lightboxImg(src, cap) {
  const img = document.createElement("img");
  img.src = src;
  lightboxContent(img, cap);
}
$("lightbox").onclick = () => lightboxClose();
window.addEventListener("keydown", (e) => {
  const lb = $("lightbox");
  if (!lb.classList.contains("show")) return;
  if (e.key === "Escape") {
    e.preventDefault();
    lightboxClose();
  } else if (e.key === "Tab") {
    // 焦点陷阱②：Tab 首尾回绕（弹层内可聚焦元素循环，不逃出模态）
    const focusables = [...lb.querySelectorAll(
        "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
      .filter((el) => el.offsetParent !== null);
    e.preventDefault();
    if (!focusables.length) { lb.focus({ preventScroll: true }); return; }
    const idx = focusables.indexOf(document.activeElement);
    const next = idx === -1
      ? (e.shiftKey ? focusables[focusables.length - 1] : focusables[0])
      : (e.shiftKey
        ? focusables[(idx - 1 + focusables.length) % focusables.length]
        : focusables[(idx + 1) % focusables.length]);
    next.focus();
  }
});

/* ── 3D 渲染（three.js，沿用电位配色） ── */
const MATERIAL_COLORS = { metal: 0xc0c8d0, substrate: 0x2e7d32 };
const BOX_COLORS = { ground: 0x556070 };
/* W8-B P2-2（2026-10-12）：视口背景/描边/网格随 body.light 两档——此前
   scene.background 硬编码深底，light 主题下画布近黑与页面浅底强反差。
   light 档：浅蓝灰底 0xe8edf5，盒描边换深灰蓝 0x2a3242（近黑描边在浅底
   上不可见），网格换 0xb9c2d0（对浅底 1.5:1，装饰性网格与 dark 档
   0x242c3d/深底同档弱对比，读数靠盒体与描边）。dark 档保持原值逐字不变。 */
const SCENE3D = {
  dark: { bg: 0x0d1118, edge: 0x0a0c10, grid: 0x242c3d },
  light: { bg: 0xe8edf5, edge: 0x2a3242, grid: 0xb9c2d0 },
};

function makeLabelSprite(THREE, text, color) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 96;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(17,20,26,0.8)";
  ctx.roundRect?.(0, 0, c.width, c.height, 12);
  ctx.fill();
  ctx.font = "bold 40px sans-serif";
  ctx.fillStyle = color || THEME_COLORS.fg.dark; // 缺省标签文字=深档前景（theme.js 单源）
  ctx.textAlign = "center";
  ctx.fillText(text, c.width / 2, 62);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sp.scale.set(20, 3.75, 1);
  return sp;
}

/* W2-B 接口诉求落地：容器级 renderer 句柄登记——重建前完全释放旧渲染器
   （WebGL 活跃上下文配额有限），并返回句柄供调用方后续释放。
   P8-2（W3-S9）：函数改 async——首行动态 import three（模块缓存命中后
   await 立即返回）；调用面（view_detail/view_recipe）均为 fire-and-forget，
   句柄返回形态从 renderer 变 Promise<renderer>（现无调用方消费返回值，
   句柄登记 _boxRenderers 语义不变）。 */
const _boxRenderers = new WeakMap();

export async function drawBoxes(container, spec) {
  const THREE = await import("three");
  const _prev = _boxRenderers.get(container);
  if (_prev) {
    _prev.setAnimationLoop(null);
    _prev.dispose();
    _prev.forceContextLoss?.();
    _boxRenderers.delete(container);
  }
  container.innerHTML = "";
  if (!spec || !spec.ok) {
    container.innerHTML = `<span class="muted">${spec ? esc(spec.errors.join("; ")) : "无几何"}</span>`;
    return null;
  }
  const w = container.clientWidth || 600, h = 420;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
  // 主题档在重绘时点现取（body.light 判定，与 drawLineChart/drawEChart 同一时机）
  const th = SCENE3D[document.body.classList.contains("light") ? "light" : "dark"];
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(th.bg);
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 2000);
  const c = [0, 0, 0];
  for (const b of spec.boxes) for (let i = 0; i < 3; i++) c[i] += (b.start_mm[i] + b.stop_mm[i]) / 2 / spec.boxes.length;
  const group = new THREE.Group();
  for (const b of spec.boxes) {
    const size = b.stop_mm.map((v, i) => Math.max(Math.abs(v - b.start_mm[i]), 0.05));
    const color = BOX_COLORS[b.name] || MATERIAL_COLORS[b.material] || 0x999999;
    const mat = new THREE.MeshPhongMaterial({
      color, transparent: b.material === "substrate", opacity: b.material === "substrate" ? 0.45 : 0.9,
    });
    // 轴向映射与下方 position 一致：模型 (x,y,z) → 场景 (x, z, y)，
    // 模型 z=高度（基板厚度轴）映射为场景竖直方向（three.js y=上）。
    // 尺寸必须与位置做同一轴交换（2026-09-15 修复：基板 120×120×0.51
    // 曾被 BoxGeometry(size[1]=120) 当高度渲染成竖立大板）。
    const geo = new THREE.BoxGeometry(size[0], size[2], size[1]);
    const mesh = new THREE.Mesh(geo, mat);
    const mid = b.start_mm.map((v, i) => (v + b.stop_mm[i]) / 2);
    mesh.position.set(mid[0] - c[0], mid[2] - c[2], mid[1] - c[1]);
    mesh.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: th.edge })));
    group.add(mesh);
  }
  const portNotes = [];
  for (const p of spec.ports || []) {
    // dir 是模型坐标向量，与盒体做同一 (x,y,z)→(x,z,y) 轴交换
    const dir = new THREE.Vector3(p.dir[0], p.dir[2], p.dir[1]);
    const pos = new THREE.Vector3(p.pos_mm[0] - c[0], p.pos_mm[2] - c[2], p.pos_mm[1] - c[1]);
    const cone = new THREE.Mesh(
      new THREE.ConeGeometry(1.6, 6, 16),
      new THREE.MeshPhongMaterial({ color: 0xffb74d }));
    cone.position.copy(pos).addScaledVector(dir, 3);
    cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    group.add(cone);
    const label = makeLabelSprite(THREE, p.name, "#ffb74d");
    label.position.copy(pos).addScaledVector(dir, 9);
    label.position.z += 4;
    group.add(label);
    portNotes.push(p.name);
  }
  scene.add(group);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(80, 120, 60);
  scene.add(dl);
  scene.add(new THREE.GridHelper(240, 24, th.grid, th.grid));
  // 相机自动取景：按模型包围盒最大维度缩放
  const bbox = new THREE.Box3().setFromObject(group);
  const maxDim = Math.max(
    bbox.max.x - bbox.min.x, bbox.max.y - bbox.min.y, bbox.max.z - bbox.min.z, 10);
  camera.position.set(60, 70, 90);
  camera.lookAt(0, 0, 0);
  orbitLike(camera, renderer.domElement, maxDim);
  renderer.setAnimationLoop(() => renderer.render(scene, camera));
  const legend = document.createElement("div");
  legend.className = "legend3d";
  const chip = (color, name) =>
    `<span class="muted"><span class="chip" style="background:#${color.toString(16).padStart(6, "0")}"></span>${name}</span>`;
  const deviceList = spec.boxes
    .map((b) => {
      const d = b.stop_mm.map((v, i) => Math.abs(v - b.start_mm[i]));
      return `${b.name}（${d.map((v) => +v.toFixed(2)).join("×")} mm）`;
    })
    .join("、");
  legend.innerHTML =
    chip(0xc0c8d0, "金属") + chip(0x556070, "地面") + chip(0x2e7d32, "基板") +
    chip(0xffb74d, "端口") +
    (portNotes.length ? `<span class="muted">　端口: ${esc(portNotes.join("、"))}</span>` : "") +
    `<div class="muted" style="margin-top:var(--space-1)">器件: ${esc(deviceList)}</div>` +
    `<div class="muted">拖动旋转 / 滚轮缩放</div>`;
  container.appendChild(legend);
  // PR-1 a11y：3D 视图图像语义（器件清单可闻；交互提示留在图例文字里）
  container.setAttribute("role", "img");
  container.setAttribute("aria-label",
    `3D 模型预览：${deviceList}${portNotes.length ? "，端口 " + portNotes.join("、") : ""}`);
  _boxRenderers.set(container, renderer);
  return renderer;
}

function orbitLike(camera, dom, maxDim = 120) {
  let dragging = false, px = 0, py = 0, theta = 0.7, phi = 1.05, radius = maxDim * 1.9;
  const apply = () => {
    camera.position.set(
      radius * Math.sin(phi) * Math.cos(theta),
      radius * Math.cos(phi),
      radius * Math.sin(phi) * Math.sin(theta));
    camera.lookAt(0, 0, 0);
  };
  apply();
  dom.onpointerdown = (e) => { dragging = true; px = e.clientX; py = e.clientY; };
  dom.onpointerup = () => (dragging = false);
  dom.onpointermove = (e) => {
    if (!dragging) return;
    theta += (e.clientX - px) * 0.008; phi -= (e.clientY - py) * 0.008;
    phi = Math.max(0.1, Math.min(3.0, phi));
    px = e.clientX; py = e.clientY; apply();
  };
  dom.onwheel = (e) => { e.preventDefault(); radius *= e.deltaY > 0 ? 1.1 : 0.9; apply(); };
}

/* ── 两级 hash 路由（aurora72 A4-C，R6 审计 R-2）── */
// 页名权威面（nav data-v 派生，26 颗含隐藏 detail）——回落语义单源在此。
const _VALID_PAGES = new Set(
    [...document.querySelectorAll("[data-v]")]
        .map((b) => b.dataset.v));
/* 两级分发器（唯一策略面）：
   - "#/page" 裸形态：旧语义零破坏——未知页名忽略（回落保持现状），有效页
     showPage；
   - "#/page/<arg>" 参数形态：parseRoute 解出 { page, arg }，页有效且注册表
     有 opener → routeOpen（opener 负责激活+数据拉取+空态/错误面板，刷新/
     前进后退/分享均经此处恢复参数态）；页有效但无 opener → 回落裸页；
     页名未知 → 忽略（与裸形态同回落）。
   hashchange 监听单源在 pages.js _bindToolsDeepLink（收编旧双监听），事件
   经 initPages 注入的 routeDispatch 回调抵达这里；boot 初载由下方
   _applyHash() 直调完成同一分发。 */
function _applyHash() {
  const r = parseRoute(location.hash);
  if (!r) return; // 空/非法形态 → 保持现状（boot 已落 dashboard）
  if (!_VALID_PAGES.has(r.page)) return; // 未知页名 → 旧回落语义保持
  if (r.arg == null) { showPage(r.page); return; } // 裸页形态（旧）
  if (!routeOpen(r.page, r.arg)) showPage(r.page); // 无 opener 页 → 回落裸页
}

initPages({
  activate, msg, api, badge, passBadge, drawLineChart, drawEChart, drawBoxes,
  lightboxImg, lightboxContent, $, plotCard: uiPlotCard,
  // P8-2（W3-S9）：工具包 THREE 键随静态 import 一并移除——唯一消费点
  // view_fieldviz drawIsoMesh 同批改 `await import("three")`（惰性取）。
  // W5-S23：读屏公告单源出口（轮询终态/状态变迁——view_tune/loopboard 消费）
  announce,
  // UI-R12：懒加载补焦桥（对象引用共享，pages.js _lazyView 包装器消费）
  _lazyFocus, pageFocusAfterRender,
  // A4-C：单源 hashchange 监听在 pages.js（旧 app.js 页级 + tools key 级
  // 双监听收编），事件经此回调回注两级分发器。
  routeDispatch: () => _applyHash(),
});
setApiNotifier(msg); // UI-R12：apiFetch 失败呈现与全局 toast 同源（aborted 形态不 toast）
showPage("dashboard");
_applyHash(); // boot 初载分发（两级：#/page 与 #/page/<arg> 同入口）
document.querySelectorAll("[data-v]").forEach((b) => {
  b.addEventListener("click", () => {
    const v = b.dataset.v;
    if (location.hash !== "#/" + v) history.replaceState(null, "", "#/" + v);
  });
});

/* ═══ W14-S2（aurora_g，R1 §面5 P9-12 / R2 Top10 #8）：离线检测 ═══
   navigator.onLine 状态翻转到时经 window online/offline 事件呈现：
   - offline → #msg 错误 toast（role=status aria-live 在壳，读屏同播）；
   - online → 恢复 toast + 当前页 PAGE_CTX.refresh 一次（断网期间失败的
     面板经既有局部刷新单源自愈；guide/import 无钩子页零动作）。
   _offlineSeen 门：只对"宣布过断网"的 online 做刷新——防启动期合成
   online 事件触发无谓重拉。纯前端零后端、零新依赖；异常全兜底
   （#105：可靠性增强面不得成为 boot 故障点）。 */
let _offlineSeen = false;
try {
  window.addEventListener("offline", () => {
    _offlineSeen = true;
    msg(t("common.offline"), false);
  });
  window.addEventListener("online", () => {
    if (!_offlineSeen) return; // 未经历断网（如启动期事件）不刷新
    _offlineSeen = false;
    msg(t("common.online"), true);
    try {
      const ctx = pageContextFor(getActiveView());
      if (ctx && typeof ctx.refresh === "function") ctx.refresh();
    } catch { /* 刷新面缺席/失败静默——toast 已给出恢复反馈 */ }
  });
} catch { /* 事件面不可用（异常宿主）静默 */ }

/* ═══ W14-S2（aurora_g，R1 §面1 P9-4 / R2 审计 §1.3 Top10 #8）：空闲预载 ═══
   boot 装配完成后把浏览器空闲时窗用满：requestIdleCallback 分三批预热
   懒加载面，高频页首访/首次 3D 渲染的 1-2s 动态 import 延迟（W7 §1 实测
   口径）归零。三批按单件重量降序，批内串行、批间让出空闲槽：
   ①vendor 重件 three（1.27MB / gzip 256,743B——任务书原列 "echarts→three→
     views"，echarts 本体是 body 尾经典阻塞 script=boot 关键路径已在档，
     无可预载面，故首支实批=three）；
   ②工作流主干视图 runs→detail（runs 湖+run 详情最高频进页对）；
   ③分析高频视图 tune→campaign→sparams。
   预载只 warm 模块缓存（视图模块零顶层 DOM 执行，node 行为钉同源保障），
   不触任何数据拉取；省流量档（saveData）/2G 网络整体跳过；import 失败
   静默——首访路径照旧，预载永不成为故障面（#105）。 */
const _IDLE_PRELOAD_BATCHES = [
  ["three"],
  ["./pages/view_runs.js", "./pages/view_detail.js"],
  ["./pages/view_tune.js", "./pages/view_campaign.js", "./pages/view_sparams.js"],
];
function _idlePreload() {
  try {
    const conn = navigator.connection;
    if (conn && (conn.saveData || String(conn.effectiveType || "").includes("2g")))
      return; // 省流量档/2G：空闲预载与用户流量利益相抵，整体跳过
  } catch { /* 连接信息不可用不阻预载 */ }
  const _idle = (fn) => {
    // requestIdleCallback 缺席降级 setTimeout（旧 Safari；宏任务让出主线程同款语义）
    if (typeof window.requestIdleCallback === "function")
      window.requestIdleCallback(fn, { timeout: 2000 });
    else window.setTimeout(fn, 300);
  };
  const runBatch = (i) => {
    const mods = _IDLE_PRELOAD_BATCHES[i];
    if (!mods) return;
    _idle(() => {
      mods.reduce(
        (chain, spec) => chain.then(() => import(spec)).catch(() => { /* 预载失败静默 */ }),
        Promise.resolve(),
      ).then(() => runBatch(i + 1));
    });
  };
  runBatch(0);
}
_idlePreload(); // 装配完成（initPages+showPage+_applyHash 已落）后触发
