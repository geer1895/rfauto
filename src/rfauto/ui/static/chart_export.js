/* rfauto 图表导出统一出口（aurora_d UI-R5）：CSV/PNG/SVG 三格式与文件名
   规范的单源。此前 plotcard.js（CSV/PNG 内联按钮 + 私有 downloadFile）与
   charts.js chartExportTools（CSV/PNG 工厂）两套装配各自拼文件名
   （`exportName + ".csv"` 无时间戳），SVG 无出口——本模块收编为：
   - exportStampName(base, ext, now)：文件名规范 `视图_指标_时间戳.扩展名`
     （base=调用方 exportName，约定"视图_指标"连字命名；时间戳=本地时间
     YYYYMMDD_HHMMSS；非法字符折叠为 "-"）。纯函数（now 可注入，node 可钉）。
   - exportCsvText / chartPngDataUrl / chartToSvgText / exportChartFile：
     内容编码单源（CSV=toCsv 产物由调用方折好传入；PNG=getDataURL 2x+主题
     底色；SVG=SSR 矢量重渲染——canvas 渲染器实例无矢量重绘路径，用
     vendored echarts ssr:true 实例按 getOption() 重放为矢量 SVG，产物
     出口剥 <script> 段=uir8 P2-8 纵深防御）。
   - mkExportButton(s)：工具条钮装配（.plotcard-tools 同款 UI/类名，
     data-export-kind 标记供复用路径重绑/主题联动定位）。
   依赖纪律：只 import dom.js/theme.js——**不 import plotcard.js/charts.js**
   （plotcard.js 与 charts.js 双向消费本模块，入边成环风险归零；CSV 文本
   由调用方用各自持有的 toCsv 折好传入）。模块顶层零 DOM 执行（node 行为
   钉可裸 import；下载动作只在点击时触达 document）。 */

import { downloadTextFile } from "./pages/dom.js";
import { THEME_COLORS, bodyIsLight, themePick } from "./theme.js";

/* 文件名规范：`视图_指标_YYYYMMDD_HHMMSS.<ext>`（本地时间；base 非法字符
   折叠 "-" 并去首尾，空/缺省兜底 "plotcard"）。 */
export function exportStampName(base, ext, now = new Date()) {
  const b = String(base || "plotcard").replace(/[^\w.-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "plotcard";
  const p = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}` +
    `_${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`;
  return `${b}_${stamp}.${ext}`;
}

/* CSV：csvText 由调用方折好（"\ufeff" + toCsv(series)，BOM 头照旧）。 */
export function exportCsvText(csvText, base) {
  downloadTextFile(exportStampName(base, "csv"), csvText,
    "text/csv;charset=utf-8");
}

/* PNG：2x + 主题底色（THEME_COLORS.plotBg 单源；实例缺失/已弃置返 null，
   调用方静默跳过——与既有 PNG 守卫同口径）。 */
export function chartPngDataUrl(chart) {
  if (!chart || chart.isDisposed()) return null;
  return chart.getDataURL({
    type: "png", pixelRatio: 2,
    backgroundColor: themePick(bodyIsLight(), THEME_COLORS.plotBg),
  });
}

/* SVG：SSR 矢量重渲染（按实例当前 getOption() 重放；echarts ≥5.3 ssr）。
   canvas 渲染器的活实例没有"重绘为矢量"路径——SSR null 实例（无 DOM 依赖）
   是唯一矢量出口；背景透明时注入主题 plotBg（PNG 同款），否则导出件白看。 */
export function chartToSvgText(chart, echartsLike) {
  if (!chart || chart.isDisposed()) return null;
  const ecs = echartsLike ||
    (typeof window !== "undefined" ? window.echarts : null);
  if (!ecs) return null;
  let ssr = null;
  try {
    ssr = ecs.init(null, null, {
      renderer: "svg", ssr: true,
      width: chart.getWidth() || 600, height: chart.getHeight() || 400,
    });
    const opt = chart.getOption();
    if (!opt.backgroundColor || opt.backgroundColor === "transparent")
      opt.backgroundColor = themePick(bodyIsLight(), THEME_COLORS.plotBg);
    ssr.setOption(opt);
    const svg = ssr.renderToSVGString();
    /* UI-R11（uir8 P2-8 信息级→出口纵深防御）：落盘前剥 <script> 段——
       series name 等外部串（外部 .sNp 文件名进图例）依赖 echarts 内部转义，
       出口再兜一道：正常产物不含 script 逐字节不变；若未来 echarts/zrender
       行为变化漏进脚本，剥离后导出，导出件喂给其他渲染器也不带脚本。 */
    return svg.replace(/<script[\s\S]*?<\/script\s*>/gi, "")
      .replace(/<script\b[^>]*>/gi, "");
  } catch {
    return null; // 导出面不阻主路径（#105 best-effort）
  } finally {
    if (ssr && !ssr.isDisposed()) ssr.dispose();
  }
}

/* 统一出口：kind → 编码+落盘。h={base|string|fn, getChart, getCsv}（点击时
   现取——复用路径 props 换代后闭包不陈旧）。失败静默跳过（导出面口径）。 */
export function exportChartFile(kind, h) {
  const base = typeof h.base === "function" ? h.base() : (h.base || "plotcard");
  if (kind === "csv") { exportCsvText(h.getCsv(), base); return; }
  const chart = h.getChart && h.getChart();
  if (kind === "png") {
    const url = chartPngDataUrl(chart);
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = exportStampName(base, "png");
    a.click();
    return;
  }
  if (kind === "svg") {
    const svg = chartToSvgText(chart);
    if (!svg) return;
    downloadTextFile(exportStampName(base, "svg"), svg, "image/svg+xml");
  }
}

/* 钮元数据（title/aria 与既有 plotCard 工具条逐字一致；SVG 为新增档）。 */
const _BTN_META = {
  csv: { label: "CSV", title: "导出数据（CSV 平铺）", aria: "导出图表数据 CSV" },
  png: { label: "PNG", title: "导出图片（PNG，2x）", aria: "导出图表图片 PNG" },
  svg: { label: "SVG", title: "导出图片（SVG，矢量）", aria: "导出图表图片 SVG" },
};

/* 单钮装配（.plotcard-tools 同款 minor.plotcard-btn；data-export-kind 供
   定位/重绑）。 */
export function mkExportButton(kind, handlers) {
  const meta = _BTN_META[kind];
  const b = document.createElement("button");
  b.className = "minor plotcard-btn";
  b.textContent = meta.label;
  b.title = meta.title;
  b.setAttribute("aria-label", meta.aria);
  b.dataset.exportKind = kind;
  b.onclick = () => exportChartFile(kind, handlers);
  return b;
}

/* 多钮装配（缺省 csv/png/svg 全量；调用方按 props 开关传入子集）。 */
export function mkExportButtons(handlers, kinds = ["csv", "png", "svg"]) {
  return kinds.map((k) => mkExportButton(k, handlers));
}
