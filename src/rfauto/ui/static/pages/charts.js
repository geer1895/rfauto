/* rfauto 工作台图表生命周期单源（aurora_d UI-R2 自 pages.js 拆出，
   逐字节搬移）：aurora36 W2-B echarts 实例缓存/resize 去重/子树释放；
   W3-B chartExportTools 导出工具条工厂；W4-C palette act-export-chart
   事件桥（监听装配走 initPages；W4-S17 起触发消费 plotcard.js 共享登记面
   ——桥登记面迁 plotCard 壳，本模块 chartExportTools 委托同一注册表）；
   P0-4 WebGL 防御式释放（_isoRenderers 与 view_fieldviz drawIsoMesh 共享
   同一 WeakMap 注册表）。
   ═══ aurora_d UI-R5：图表能力统一深化 ═══
   - 调用面归一：plotCard 内建同容器复用落地（plotcard.js，W2-B 接口诉求
     闭合）——plotCardCached 降级为零破坏薄委托（tune/tools 两调用点不动），
     全站图表渲染单一入口；绘参选项（S 参数 dB/相位/线性、Smith、热图色带）
     收敛到本层 sparamChartProps/smithChartTheme/heatColormap 选项工厂。
   - 万点级降采样：实现单源在 plotcard.js（min-max 包络抽稀=保形默认档，
     LTTB=感知备选档；共享网格分组多迹线同索引），plotCardOption 接缝生效；
     本层 re-export 阈值配置面（全站单源）。
   - 导出统一：CSV/PNG/SVG 单源出口 chart_export.js（文件名
     `视图_指标_时间戳`），chartExportTools 收编（补 SVG 档）。
   - 主题联动：theme.js 四态切换 → body.light 翻转 → MutationObserver
     → refreshThemeCharts() 对全部存活 plotCard 壳重放 option（新档调色板
     +轴/文字色，setOption notMerge）；midnight↔ocean 共用深档不重放。 */

import {
  downsamplePlotSeries, fireRecentChartExport, getDefaultMaxPoints,
  lttbIndices, minmaxIndices, plotCardOption, plotCardShellEntries,
  registerRecentChartExport, setDefaultMaxPoints, toCsv,
  DEFAULT_MAX_POINTS,
} from "../plotcard.js";
import {
  HEAT_BAND, THEME_COLORS, bodyIsLight, chartPalette, smithPalette, themePick,
} from "../theme.js";
import { exportChartFile, exportCsvText } from "../chart_export.js";
import { T } from "./context.js";

/* 阈值/算法面 re-export：降采样单源在 plotcard.js，此处并入 charts 层
   统一出口（调用方只认 charts.js 一层）。 */
export {
  DEFAULT_MAX_POINTS, downsamplePlotSeries, getDefaultMaxPoints, lttbIndices,
  minmaxIndices, setDefaultMaxPoints,
};

/* ═══ aurora36 W2-B：前端资源生命周期（R1 审计 P0-4/P0-5/P2-13）═════════
   本块 = pages.js 调用侧自救面。app.js drawBoxes / plotcard.js plotCard 归
   W2-C，接口诉求见各函数注释与席位报告（drawBoxes 返回 renderer 句柄 +
   dispose；plotCard 内建同容器 setOption 复用 + resize 监听去重）。 */

/* P0-5：echarts 实例缓存（容器 → 存活实例）与 resize 监听去重标记。
   直接 window.echarts.init 的新实例每次还挂一个永不清理的 window resize
   监听——同容器重复渲染（轮询/改参/切数据）必须复用实例并去重监听。 */
const _liveCharts = new WeakMap(); // 容器 el → echarts 实例
const _resizeBound = new WeakSet(); // 已挂 resize 的容器（一容器至多一个监听）

/* 实例缓存守卫的 init：同容器已有存活实例 → 原样复用（调用方随后
   setOption(..., true) 整体替换 option）；否则清容器残骸后新 init 并登记。
   只允许经本函数取实例（保持"init 调用点有实例缓存守卫"不变量）。 */
export function echartsInitCached(el) {
  const prev = _liveCharts.get(el);
  if (prev && !prev.isDisposed() && prev.getDom() === el) return prev;
  if (prev && !prev.isDisposed()) prev.dispose(); // 容器已换血：旧实例先释放
  _liveCharts.delete(el);
  el.innerHTML = ""; // 新建路径才清容器（复用路径保留图表 DOM 原地刷新）
  const chart = window.echarts.init(el);
  _liveCharts.set(el, chart);
  return chart;
}

/* resize 监听去重：同容器只挂一个（WeakSet 标记）；回调经缓存取当前实例，
   实例被 dispose 后自动跳过。 */
export function bindChartResize(el) {
  if (_resizeBound.has(el)) return; // 去重标记：此容器已挂过监听
  _resizeBound.add(el);
  window.addEventListener("resize", () => {
    const c = _liveCharts.get(el);
    if (c && !c.isDisposed()) c.resize();
  });
}

/* 容器子树重建（innerHTML 换血）前：释放挂在旧子树容器上的 echarts 实例
   （缓存键随元素走；不显式 dispose 则旧实例连同 canvas/zrender 滞留堆中）。
   W3-S12（P-5）：plotCard 壳登记面同口径释放——四管线逃生舱迁移后场/远场
   三处容器换血的旧实例经 _plotShells（WeakMap 直查不可及）登记，走
   WeakRef 遍历面补清；isDisposed 守卫幂等（与上方旧管线双覆盖无害），
   同容器重建路径（plotCard 内建）随后摘除其 resize 监听。 */
export function disposeChartsIn(root) {
  if (!root || !root.querySelectorAll) return;
  for (const el of [root, ...root.querySelectorAll("*")]) {
    const c = _liveCharts.get(el);
    if (c && !c.isDisposed()) c.dispose();
  }
  for (const { el, shell } of plotCardShellEntries()) {
    if (!root.contains(el)) continue;
    if (shell.chart && !shell.chart.isDisposed()) shell.chart.dispose();
  }
}
/* P0-5（tune 3s 轮询）→ UI-R5 归一收编：plotCard 已内建"同容器存活壳
   setOption 复用 + aria 同步 + 导出钮 handlers 现取"（plotcard.js，W2-B
   接口诉求闭合），本包装降级为**零破坏薄委托**——tune/tools 两调用点与
   历史名保留，全站图表渲染单一入口（T.plotCard=uiPlotCard 注入主题 ctx）。 */
export function plotCardCached(el, props) {
  return T.plotCard(el, props);
}
/* ═══ aurora_d UI-R5：主题联动（四态切换 → 存活 plotCard 配色跟随）═════
   此前图表配色只在渲染时点取 bodyIsLight()——切主题后已渲染的图保持旧配色，
   直到下次轮询/重入才跟上（sparams/timeline 等无轮询页永久滞后）。本块：
   - refreshThemeCharts()：经 plotCardShellEntries()（plotcard.js WeakRef
     遍历面，离场容器惰性清理）对全部存活壳以新档 {light,
     palette:chartPalette} 重放 plotCardOption（notMerge 整体替换）——轴/
     图例/系列色一拍跟上；bodyIsLight 未翻档（midnight↔ocean 共用深档，
     theme.js 已固化结论）时零动作；
   - _bindThemeRefresh()：MutationObserver 盯 body.light 翻转（applyThemeDom
     双写单点，覆盖按钮四态循环与 system 态跟随两条路径），initPages 装配
     一次（模块顶层零 DOM 依赖，node 行为钉经 registerPlotCardShell 直注
     假壳驱动 refreshThemeCharts）。 */
let _themeObsBound = false;
let _lastLight = null;

/* 重放全部存活 plotCard 壳（返回重放数；同档跳过返回 0）。 */
export function refreshThemeCharts() {
  const light = bodyIsLight();
  if (_lastLight !== null && light === _lastLight) return 0;
  _lastLight = light;
  const theme = { light, palette: chartPalette(light) };
  let n = 0;
  for (const { el, shell } of plotCardShellEntries()) {
    if (typeof document !== "undefined" && document.contains &&
        !document.contains(el)) continue; // 离场容器（WeakRef 面惰性清理）
    if (!shell.chart || shell.chart.isDisposed()) continue;
    shell.ctx = theme;
    shell.chart.setOption(plotCardOption(shell.props, theme), true);
    n += 1;
  }
  return n;
}

export function _bindThemeRefresh() {
  if (_themeObsBound || typeof document === "undefined" || !document.body ||
      typeof MutationObserver === "undefined") return;
  _themeObsBound = true;
  _lastLight = bodyIsLight();
  new MutationObserver(() => { refreshThemeCharts(); })
    .observe(document.body, { attributes: true, attributeFilter: ["class"] });
}
/* ═══ aurora_d UI-R5：绘参选项工厂（S 参数 dB/相位/线性、Smith、热图色带）═══
   此前各视图手拼 props（ylabel 口径散置、crosshair/zoom 档各处复制）——
   预设收敛本层单源；消费面渐进迁移（view_detail 已接，view_sparams 因
   并行席位在制缓接——工厂语义与其现拼逐键同形）。 */
export const SPARAM_MODES = ["db", "deg", "linear"];
export const SPARAM_YLABEL = { db: "dB", deg: "相位（deg）", linear: "线性" };

/* 服务层曲线形态（{name, freq_ghz, y}）→ plotCard series 条目单源映射。 */
export function sparamSeries(curves) {
  return (curves || []).map((c) => ({ name: c.name, x: c.freq_ghz, y: c.y }));
}

/* S 参数曲线卡 props 预设：dB/相位/线性同族（GHz 横轴+十字线+缩放+降采样
   由 plotCardOption 接缝按阈值自动生效）。 */
export function sparamChartProps(
  { mode = "db", curves = [], height = "340px", exportName = "sparams", maxPoints } = {},
) {
  return {
    series: sparamSeries(curves),
    xlabel: "GHz",
    ylabel: SPARAM_YLABEL[mode] || SPARAM_YLABEL.db,
    height, zoom: true, crosshair: true, exportName,
    ...(maxPoints != null ? { maxPoints } : {}),
  };
}

/* Smith 圆图主题对（网格色+六档轨迹色）——drawSmith 消费，颜色档单源仍在
   theme.js（smithPalette/smithGrid），此处只做"一对一次取齐"的工厂面。 */
export function smithChartTheme(light) {
  return {
    grid: themePick(light, THEME_COLORS.smithGrid),
    palette: smithPalette(light),
  };
}

/* 热图色带透传（theme.js HEAT_BAND 单源；工具页/场切片/远场 3D 色图口径
   的 charts 层出口）。 */
export function heatColormap() {
  return HEAT_BAND;
}
/* ═══ aurora36 W3-B：自研管线图表导出 + 可排序表格（R1 §③ / P1-7）═════════ */

/* 导出工具条小工厂（不重复装配代码）：与 plotCard 工具条同款 UI/类名
   （.plotcard-tools > button.minor.plotcard-btn）。
   逐处评估结论（W3-B 席位报告；W4-S17 更新）：plotcard.js builder 能力面 =
   笛卡尔 line/scatter/band——polar / Smith 隐藏轴等比坐标 / 场切片
   custom+visualMap / 远场 θ×φ heatmap 均不在其上，四管线已于 W3-S12（R6
   审计 P-5）经 plotCard props.option 逃生舱整接入壳（导出随壳内建），
   chartExportTools 现存消费者=dashboard 甜甜圈（refEl=null append 形态）。
   W4-S17（W3-S12 建议①登记面收窄）：桥"最近装配"登记迁 plotCard 壳
   （plotcard.js registerRecentChartExport 单源）——本工厂退役自有 WeakRef
   闭包，PNG 钮装配后委托同一登记面（甜甜圈与 plotCard 壳喂同一注册表，
   触发面见下方事件桥注释）。UI-R5 收编：CSV/PNG/SVG 编码与文件名走
   chart_export.js 统一出口（`视图_指标_时间戳`），本工厂补 SVG 档；
   实例缺失或已 dispose 时点导出静默跳过（统一出口内置同口径守卫）。 */
export function chartExportTools(host, refEl, opts) {
  const { name, getChart, getCsvSeries } = opts;
  const tools = document.createElement("div");
  tools.className = "plotcard-tools";
  const mk = (text, title, aria, onclick) => {
    const b = document.createElement("button");
    b.className = "minor plotcard-btn";
    b.textContent = text;
    b.title = title;
    b.setAttribute("aria-label", aria);
    b.onclick = onclick;
    tools.appendChild(b);
    return b;
  };
  const csvBtn = mk("CSV", "导出数据（CSV 平铺）", "导出图表数据 CSV", () =>
    exportCsvText("\ufeff" + toCsv(getCsvSeries()), name));
  csvBtn.dataset.exportKind = "csv";
  const pngBtn = mk("PNG", "导出图片（PNG，2x）", "导出图表图片 PNG", () =>
    exportChartFile("png", { base: name, getChart }));
  pngBtn.dataset.exportKind = "png";
  const svgBtn = mk("SVG", "导出图片（SVG，矢量）", "导出图表图片 SVG", () =>
    exportChartFile("svg", { base: name, getChart }));
  svgBtn.dataset.exportKind = "svg";
  registerRecentChartExport(pngBtn); // W4-S17：登记面迁 plotCard 壳（同一注册表）
  host.insertBefore(tools, refEl);
  return tools;
}
/* palette act-export-chart 事件桥（跨席契约，palette 侧发射端固定）：
   监听 window 级 CustomEvent("rfauto:export-chart")（**契约：event 名固定、
   无 payload**）→ plotcard.js fireRecentChartExport() 触发"最近渲染"图表的
   PNG 导出（W4-S17 起登记面=plotCard 壳首绘/复用 + chartExportTools 甜甜圈
   委托，同一注册表；此前=chartExportTools 装配面独占——四管线入壳后只剩
   甜甜圈一个喂食点，非甜甜圈页桥恒空转）。图表已弃置/工具条已随页换血
   离场时，PNG onclick 内的 isDisposed 守卫与登记侧 document.contains 探针
   各自静默跳过（统一出口内置，不弹错）。
   监听装配走 initPages（本模块顶层零 DOM 依赖，node 行为钉 import 可跑）。 */
let _exportEvtBound = false;
export function _bindExportChartEvent() {
  if (_exportEvtBound || typeof window === "undefined" || !window.addEventListener) return;
  _exportEvtBound = true;
  window.addEventListener("rfauto:export-chart", () => {
    fireRecentChartExport();
  });
}
/* ═══ aurora36 W4-C 块结束 ═══ */
/* P0-4：WebGL 防御式释放（调用侧能做的最大自救）。
   ① 本文件自有管线（drawIsoMesh）登记的 renderer → 停动画循环 + dispose +
      forceContextLoss（完全释放，自愈面）；
   ② 无句柄 canvas（app.js drawBoxes 产物；浏览器活跃 WebGL 上下文上限
      ~16 个，超限即 context-lost）→ 经 WEBGL_lose_context 强制弃置上下文
      归还配额——JS 堆侧（渲染循环闭包/scene）无句柄不可及，根治需下方
      接口诉求落地。
   【接口诉求（转 W2-C / app.js 属主）】drawBoxes 应返回 renderer 句柄，并
   在重建前对旧 renderer 做 setAnimationLoop(null)+dispose()+forceContextLoss()；
   届时本函数 ②分支与两处 T.drawBoxes 调用侧前置可整体删除。 */
export const _isoRenderers = new WeakMap(); // 容器 → drawIsoMesh 的 three.js renderer

export function releaseWebGLIn(root) {
  if (!root || !root.querySelectorAll) return;
  for (const el of [root, ...root.querySelectorAll("*")]) {
    const r = _isoRenderers.get(el);
    if (r) {
      r.setAnimationLoop(null);
      r.dispose();
      if (r.forceContextLoss) r.forceContextLoss();
      _isoRenderers.delete(el);
    }
  }
  for (const cv of root.querySelectorAll("canvas")) {
    try {
      // 交给本函数的容器内 canvas 只可能来自 3D 管线（WebGL），getContext
      // 不会凭空造出多余上下文；已丢上下文时 loseContext 幂等
      const gl = cv.getContext("webgl2") || cv.getContext("webgl");
      const lc = gl && gl.getExtension("WEBGL_lose_context");
      if (lc) lc.loseContext();
    } catch { /* 上下文已丢失等，best-effort（清理面不阻主路径，#105） */ }
  }
}
